import sqlite3
import json
import os
from datetime import datetime
from typing import List, Optional
from models import PassIdentifier, Rank, User, Faction, Nation, UserPass

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
                nation_id INTEGER
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

    async def create_user_pass(self, user_id: int, expiry_date: datetime) -> Optional[UserPass]:
        user = await self.get_user(user_id)
        if not user:
            return None

        identifier = await self.generate_pass_identifier(user.faction_id, user.nation_id)
        
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
            identifier.colored_part
        ))
        self.conn.commit()

        return UserPass(
            user_id=user_id,
            faction_id=user.faction_id,
            nation_id=user.nation_id,
            issue_date=datetime.now(),
            expiry_date=expiry_date,
            pass_identifier=identifier
        )

    # Add more methods for pass verification and management...
