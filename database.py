import sqlite3
import json
import os
from datetime import datetime
from typing import List, Optional
from models import FactionPermission, PassIdentifier, Rank, User, Faction, Nation, UserPass

class Database:
    def __init__(self):
        self.conn = sqlite3.connect('megatropo.db')
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 2500,
                faction_id INTEGER,
                nation_id INTEGER,
                rank_id INTEGER  -- Add this line to ensure the rank_id column exists
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS factions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                owner_id INTEGER,
                balance REAL DEFAULT 0,
                nation_id INTEGER,
                ranks TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS nations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                owner_id INTEGER,
                balance REAL DEFAULT 0,
                allies TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ranks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faction_id INTEGER,
                name TEXT,
                priority INTEGER,
                permissions TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_invites (
                user_id INTEGER,
                faction_id INTEGER,
                PRIMARY KEY (user_id, faction_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pass_identifiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faction_id INTEGER,
                nation_id INTEGER,
                colorless_part TEXT,
                UNIQUE(faction_id, nation_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_passes (
                user_id INTEGER PRIMARY KEY,
                faction_id INTEGER,
                nation_id INTEGER,
                issue_date TEXT,
                expiry_date TEXT,
                colored_part TEXT,
                faction_rank TEXT,
                nation_rank TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS entity_images (
                entity_type TEXT,
                entity_id INTEGER,
                image_path TEXT,
                PRIMARY KEY (entity_type, entity_id)
            )
        ''')
        self.conn.commit()

    async def get_user(self, user_id: int) -> User:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute('INSERT INTO users (id) VALUES (?)', (user_id,))
            self.conn.commit()
            return User(id=user_id)
        return User(id=row[0], balance=row[1], faction_id=row[2], nation_id=row[3])

    async def modify_balance(self, user_id: int, amount: float):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET balance = balance + ? WHERE id = ?', (amount, user_id))
        self.conn.commit()

    async def create_rank(self, faction_id: int, name: str, priority: int, permissions: List[str]) -> Optional[int]:
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO ranks (faction_id, name, priority, permissions) VALUES (?, ?, ?, ?)',
                (faction_id, name, priority, json.dumps(permissions))
            )
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.Error:
            return None

    async def add_pending_invite(self, user_id: int, faction_id: int) -> bool:
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO pending_invites (user_id, faction_id) VALUES (?, ?)',
                (user_id, faction_id)
            )
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    async def get_faction_member_rank(self, faction_id: int, user_id: int) -> Optional[Rank]:
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT r.* FROM ranks r
            JOIN users u ON u.rank_id = r.id
            WHERE u.faction_id = ? AND u.id = ?
        ''', (faction_id, user_id))
        row = cursor.fetchone()
        if row:
            return Rank(
                name=row[2],
                priority=row[3],
                permissions=set(json.loads(row[4]))
            )
        return None

    async def get_faction(self, faction_id: int) -> Optional[Faction]:
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT f.*, COUNT(u.id) as member_count 
            FROM factions f 
            LEFT JOIN users u ON u.faction_id = f.id 
            WHERE f.id = ?
            GROUP BY f.id
        ''', (faction_id,))
        row = cursor.fetchone()
        if row:
            return Faction(
                id=row[0],
                name=row[1],
                owner_id=row[2],
                balance=row[3],
                nation_id=row[4],
                members=[],  # We'll fetch members separately if needed
                ranks=json.loads(row[5]) if row[5] else {}
            )
        return None

    async def get_faction_by_name(self, name: str) -> Optional[Faction]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM factions WHERE name = ?', (name,))
        row = cursor.fetchone()
        if row:
            return await self.get_faction(row[0])
        return None

    async def get_nation(self, nation_id: int) -> Optional[Nation]:
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT n.*, COUNT(f.id) as faction_count 
            FROM nations n 
            LEFT JOIN factions f ON f.nation_id = n.id 
            WHERE n.id = ?
            GROUP BY n.id
        ''', (nation_id,))
        row = cursor.fetchone()
        if row:
            return Nation(
                id=row[0],
                name=row[1],
                owner_id=row[2],
                balance=row[3],
                allies=json.loads(row[4]) if row[4] else [],
                factions=[]  # We'll fetch factions separately if needed
            )
        return None

    async def get_nation_by_name(self, name: str) -> Optional[Nation]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM nations WHERE name = ?', (name,))
        row = cursor.fetchone()
        if row:
            return await self.get_nation(row[0])
        return None

    async def get_faction_members(self, faction_id: int) -> List[int]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM users WHERE faction_id = ?', (faction_id,))
        return [row[0] for row in cursor.fetchall()]

    async def add_alliance(self, nation1_id: int, nation2_id: int) -> bool:
        cursor = self.conn.cursor()
        try:
            # Add nation2 to nation1's allies
            nation1 = await self.get_nation(nation1_id)
            allies1 = nation1.allies or []
            if nation2_id not in allies1:
                allies1.append(nation2_id)
                cursor.execute(
                    'UPDATE nations SET allies = ? WHERE id = ?',
                    (json.dumps(allies1), nation1_id)
                )

            # Add nation1 to nation2's allies
            nation2 = await self.get_nation(nation2_id)
            allies2 = nation2.allies or []
            if nation1_id not in allies2:
                allies2.append(nation1_id)
                cursor.execute(
                    'UPDATE nations SET allies = ? WHERE id = ?',
                    (json.dumps(allies2), nation2_id)
                )

            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    async def remove_alliance(self, nation1_id: int, nation2_id: int) -> bool:
        cursor = self.conn.cursor()
        try:
            # Remove nation2 from nation1's allies
            nation1 = await self.get_nation(nation1_id)
            allies1 = nation1.allies or []
            if nation2_id in allies1:
                allies1.remove(nation2_id)
                cursor.execute(
                    'UPDATE nations SET allies = ? WHERE id = ?',
                    (json.dumps(allies1), nation1_id)
                )

            # Remove nation1 from nation2's allies
            nation2 = await self.get_nation(nation2_id)
            allies2 = nation2.allies or []
            if nation1_id in allies2:
                allies2.remove(nation1_id)
                cursor.execute(
                    'UPDATE nations SET allies = ? WHERE id = ?',
                    (json.dumps(allies2), nation2_id)
                )

            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    async def transfer_money(self, from_type: str, from_id: int, to_type: str, to_id: int, amount: float) -> bool:
        cursor = self.conn.cursor()
        try:
            # Check source balance
            if from_type == 'faction':
                cursor.execute('SELECT balance FROM factions WHERE id = ?', (from_id,))
            else:  # nation
                cursor.execute('SELECT balance FROM nations WHERE id = ?', (from_id,))
            
            source_balance = cursor.fetchone()[0]
            if source_balance < amount:
                return False

            # Perform transfer
            if from_type == 'faction':
                cursor.execute('UPDATE factions SET balance = balance - ? WHERE id = ?', (amount, from_id))
            else:  # nation
                cursor.execute('UPDATE nations SET balance = balance - ? WHERE id = ?', (amount, from_id))

            if to_type == 'faction':
                cursor.execute('UPDATE factions SET balance = balance + ? WHERE id = ?', (amount, to_id))
            else:  # nation
                cursor.execute('UPDATE nations SET balance = balance + ? WHERE id = ?', (amount, to_id))

            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    async def store_entity_image(self, entity_type: str, entity_id: int, image_data: bytes) -> bool:
        path = f"images/{entity_type}_{entity_id}.png"
        os.makedirs("images", exist_ok=True)
        
        try:
            with open(path, "wb") as f:
                f.write(image_data)
            
            cursor = self.conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO entity_images (entity_type, entity_id, image_path) VALUES (?, ?, ?)',
                (entity_type, entity_id, path)
            )
            self.conn.commit()
            return True
        except Exception:
            return False

    async def generate_pass_identifier(self, faction_id: Optional[int], nation_id: Optional[int]) -> PassIdentifier:
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT colorless_part FROM pass_identifiers WHERE faction_id = ? AND nation_id = ?',
            (faction_id, nation_id)
        )
        row = cursor.fetchone()
        
        if not row:
            # Generate new colorless part (simplified for example)
            import random
            colorless = format(random.getrandbits(24), '06x')
            
            cursor.execute(
                'INSERT INTO pass_identifiers (faction_id, nation_id, colorless_part) VALUES (?, ?, ?)',
                (faction_id, nation_id, colorless)
            )
            self.conn.commit()
        else:
            colorless = row[0]

        # Generate unique colored part for user
        colored = format(random.getrandbits(24), '06x')
        
        return PassIdentifier(colorless, colored, faction_id, nation_id)

    async def get_pass_identifier(self, faction_id: Optional[int], nation_id: Optional[int]) -> Optional[str]:
        """Get existing colorless part for faction/nation combination"""
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT colorless_part FROM pass_identifiers WHERE faction_id = ? AND nation_id = ?',
            (faction_id, nation_id)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    async def create_user_pass(self, user_id: int, expiry_date: datetime) -> Optional[UserPass]:
        user = await self.get_user(user_id)
        if not user:
            return None

        # Get or create identifier
        colorless_part = await self.get_pass_identifier(user.faction_id, user.nation_id)
        if not colorless_part:
            # Generate new colorless part with fixed length
            import random
            colorless_part = '0' * 72  # Default to all zeros
            if user.faction_id or user.nation_id:
                random_part = ''.join(format(random.randint(0, 15), 'x') for _ in range(24))
                colorless_part = random_part + '0' * 48  # Pad with zeros

        # Generate colored part for user with fixed length
        import hashlib
        hash_input = f"user_{user_id}_{datetime.now().strftime('%Y%m')}"
        hash_hex = hashlib.sha256(hash_input.encode()).hexdigest()
        colored_part = hash_hex[:72].ljust(72, '0')  # Ensure exactly 72 chars
        
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO user_passes 
            (user_id, faction_id, nation_id, issue_date, expiry_date, colored_part)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            user_id, 
            user.faction_id,
            user.nation_id,
            datetime.now().isoformat(),
            expiry_date.isoformat(),
            colored_part
        ))
        self.conn.commit()

        return UserPass(
            user_id=user_id,
            faction_id=user.faction_id,
            nation_id=user.nation_id,
            issue_date=datetime.now(),
            expiry_date=expiry_date,
            pass_identifier=PassIdentifier(
                colorless_part=colorless_part,
                colored_part=colored_part,
                faction_id=user.faction_id,
                nation_id=user.nation_id
            )
        )

    async def get_user_faction(self, user_id: int) -> Optional[Faction]:
        """Get a user's faction by their user ID"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT faction_id FROM users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        
        if not row or not row[0]:  # If user has no faction
            return None
            
        return await self.get_faction(row[0])

    async def get_user_pass(self, user_id: int) -> Optional[UserPass]:
        """Get a user's current pass"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT up.*, pi.colorless_part
            FROM user_passes up
            LEFT JOIN pass_identifiers pi ON (
                pi.faction_id = up.faction_id AND 
                pi.nation_id = up.nation_id
            )
            WHERE up.user_id = ?
        ''', (user_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
            
        return UserPass(
            user_id=row[0],
            faction_id=row[1],
            nation_id=row[2],
            issue_date=datetime.fromisoformat(row[3]),
            expiry_date=datetime.fromisoformat(row[4]),
            pass_identifier=PassIdentifier(
                colorless_part=row[8] or '000000',
                colored_part=row[5],
                faction_id=row[1],
                nation_id=row[2]
            ),
            faction_rank=row[6],
            nation_rank=row[7]
        )

    async def revoke_pass(self, user_id: int) -> bool:
        """Revoke a user's pass"""
        cursor = self.conn.cursor()
        try:
            cursor.execute('DELETE FROM user_passes WHERE user_id = ?', (user_id,))
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    async def update_pass_ranks(self, user_id: int, faction_rank: Optional[str] = None, nation_rank: Optional[str] = None) -> bool:
        """Update the rank information on a user's pass"""
        cursor = self.conn.cursor()
        try:
            updates = []
            params = []
            if faction_rank is not None:
                updates.append("faction_rank = ?")
                params.append(faction_rank)
            if nation_rank is not None:
                updates.append("nation_rank = ?")
                params.append(nation_rank)
            
            if not updates:
                return False
                
            params.append(user_id)
            cursor.execute(
                f'UPDATE user_passes SET {", ".join(updates)} WHERE user_id = ?',
                tuple(params)
            )
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    async def extend_pass_validity(self, user_id: int, days: int) -> bool:
        """Extend the validity of a user's pass"""
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                UPDATE user_passes 
                SET expiry_date = datetime(expiry_date, ?) 
                WHERE user_id = ?
            ''', (f'+{days} days', user_id))
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    async def get_expired_passes(self) -> List[int]:
        """Get list of user IDs with expired passes"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT user_id FROM user_passes 
            WHERE datetime(expiry_date) < datetime('now')
        ''')
        return [row[0] for row in cursor.fetchall()]

    async def regenerate_faction_pass_identifier(self, faction_id: int) -> bool:
        """Generate a new pass identifier for a faction (costs 50)"""
        faction = await self.get_faction(faction_id)
        if not faction or faction.balance < 50:
            return False
            
        cursor = self.conn.cursor()
        try:
            import random
            new_colorless = format(random.getrandbits(24), '06x')
            
            cursor.execute('''
                INSERT OR REPLACE INTO pass_identifiers 
                (faction_id, nation_id, colorless_part) 
                VALUES (?, NULL, ?)
            ''', (faction_id, new_colorless))
            
            cursor.execute(
                'UPDATE factions SET balance = balance - 50 WHERE id = ?',
                (faction_id,)
            )
            
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    async def regenerate_nation_pass_identifier(self, nation_id: int) -> bool:
        """Generate a new pass identifier for a nation (costs 200)"""
        nation = await self.get_nation(nation_id)
        if not nation or nation.balance < 200:
            return False
            
        cursor = self.conn.cursor()
        try:
            import random
            new_colorless = format(random.getrandbits(24), '06x')
            
            cursor.execute('''
                INSERT OR REPLACE INTO pass_identifiers 
                (faction_id, nation_id, colorless_part) 
                VALUES (NULL, ?, ?)
            ''', (nation_id, new_colorless))
            
            cursor.execute(
                'UPDATE nations SET balance = balance - 200 WHERE id = ?',
                (nation_id,)
            )
            
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    async def create_faction(self, name: str, owner_id: int) -> bool:
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO factions (name, owner_id) VALUES (?, ?)',
                (name, owner_id)
            )
            faction_id = cursor.lastrowid
            await self.create_default_ranks_for_faction(faction_id)
            
            # First get the owner rank_id
            cursor.execute('SELECT id FROM ranks WHERE faction_id = ? AND name = "Owner"', (faction_id,))
            owner_rank_id = cursor.fetchone()[0]
            
            # Then update the user with both faction_id and rank_id
            cursor.execute(
                'UPDATE users SET faction_id = ?, rank_id = ? WHERE id = ?',
                (faction_id, owner_rank_id, owner_id)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    async def create_nation(self, name: str, owner_id: int) -> bool:
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO nations (name, owner_id) VALUES (?, ?)',
                (name, owner_id)
            )
            nation_id = cursor.lastrowid
            await self.create_default_ranks_for_nation(nation_id)
            cursor.execute(
                'UPDATE users SET nation_id = ? WHERE id = ?',
                (nation_id, owner_id)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    async def convert_faction_to_nation(self, faction_id: int, name: str) -> bool:
        cursor = self.conn.cursor()
        try:
            cursor.execute('SELECT owner_id FROM factions WHERE id = ?', (faction_id,))
            owner_row = cursor.fetchone()
            if not owner_row:
                return False
            
            cursor.execute(
                'INSERT INTO nations (name, owner_id) VALUES (?, ?)',
                (name, owner_row[0])
            )
            nation_id = cursor.lastrowid
            await self.create_default_ranks_for_nation(nation_id)
            
            cursor.execute(
                'UPDATE factions SET nation_id = ? WHERE id = ?',
                (nation_id, faction_id)
            )
            cursor.execute(
                'UPDATE users SET nation_id = ? WHERE faction_id = ?',
                (nation_id, faction_id)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    async def remove_rank(self, entity_id: int, rank_name: str) -> bool:
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                'DELETE FROM ranks WHERE faction_id = ? AND name = ?',
                (entity_id, rank_name)
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error:
            return False

    async def edit_rank(self, entity_id: int, rank_name: str, new_name: Optional[str], new_priority: Optional[int], permissions: List[str]) -> bool:
        cursor = self.conn.cursor()
        try:
            updates = []
            params = []
            if new_name:
                updates.append("name = ?")
                params.append(new_name)
            if new_priority is not None:
                updates.append("priority = ?")
                params.append(new_priority)
            if permissions:
                updates.append("permissions = ?")
                params.append(json.dumps(permissions))
            
            if not updates:
                return False
                
            params.append(entity_id)
            params.append(rank_name)
            cursor.execute(
                f'UPDATE ranks SET {", ".join(updates)} WHERE faction_id = ? AND name = ?',
                tuple(params)
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error:
            return False

    async def disband_faction(self, faction_id: int) -> bool:
        cursor = self.conn.cursor()
        try:
            cursor.execute('DELETE FROM factions WHERE id = ?', (faction_id,))
            cursor.execute('UPDATE users SET faction_id = NULL WHERE faction_id = ?', (faction_id,))
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    async def disband_nation(self, nation_id: int) -> bool:
        cursor = self.conn.cursor()
        try:
            cursor.execute('DELETE FROM nations WHERE id = ?', (nation_id,))
            cursor.execute('UPDATE users SET nation_id = NULL WHERE nation_id = ?', (nation_id,))
            cursor.execute('UPDATE factions SET nation_id = NULL WHERE nation_id = ?', (nation_id,))
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    async def create_default_ranks_for_faction(self, faction_id: int):
        cursor = self.conn.cursor()
        default_ranks = [
            ("Owner", 0, [FactionPermission.MANAGE_MONEY.name, FactionPermission.ADD_MEMBERS.name, FactionPermission.MANAGE_RANKS.name, FactionPermission.MANAGE_ALLIANCES.name, FactionPermission.MANAGE_ANNOUNCEMENTS.name]),
            ("Leader", 1, [FactionPermission.MANAGE_MONEY.name, FactionPermission.ADD_MEMBERS.name, FactionPermission.MANAGE_RANKS.name, FactionPermission.MANAGE_ALLIANCES.name]),
            ("Chief", 2, [FactionPermission.ADD_MEMBERS.name, FactionPermission.MANAGE_RANKS.name]),
            ("Member", 3, [])
        ]
        for name, priority, permissions in default_ranks:
            cursor.execute(
                'INSERT INTO ranks (faction_id, name, priority, permissions) VALUES (?, ?, ?, ?)',
                (faction_id, name, priority, json.dumps(permissions))
            )
        self.conn.commit()

    async def create_default_ranks_for_nation(self, nation_id: int):
        cursor = self.conn.cursor()
        default_ranks = [
            ("Owner", 0, [FactionPermission.MANAGE_MONEY.name, FactionPermission.ADD_MEMBERS.name, FactionPermission.MANAGE_RANKS.name, FactionPermission.MANAGE_ALLIANCES.name, FactionPermission.MANAGE_ANNOUNCEMENTS.name]),
            ("Leader", 1, [FactionPermission.MANAGE_MONEY.name, FactionPermission.ADD_MEMBERS.name, FactionPermission.MANAGE_RANKS.name, FactionPermission.MANAGE_ALLIANCES.name]),
            ("Chief", 2, [FactionPermission.ADD_MEMBERS.name, FactionPermission.MANAGE_RANKS.name]),
            ("Member", 3, [])
        ]
        for name, priority, permissions in default_ranks:
            cursor.execute(
                'INSERT INTO ranks (faction_id, name, priority, permissions) VALUES (?, ?, ?, ?)',
                (nation_id, name, priority, json.dumps(permissions))
            )
        self.conn.commit()

    async def accept_faction_invite(self, user_id: int, faction_id: int) -> bool:
        cursor = self.conn.cursor()
        try:
            cursor.execute('DELETE FROM pending_invites WHERE user_id = ? AND faction_id = ?', (user_id, faction_id))
            if cursor.rowcount == 0:
                return False  # No pending invite found

            cursor.execute('UPDATE users SET faction_id = ? WHERE id = ?', (faction_id, user_id))
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    async def accept_nation_invite(self, user_id: int, nation_id: int) -> bool:
        cursor = self.conn.cursor()
        try:
            cursor.execute('DELETE FROM pending_invites WHERE user_id = ? AND faction_id = ?', (user_id, nation_id))
            if cursor.rowcount == 0:
                return False  # No pending invite found

            cursor.execute('UPDATE users SET nation_id = ? WHERE id = ?', (nation_id, user_id))
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False
