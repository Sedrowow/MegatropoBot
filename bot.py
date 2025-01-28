import os
import discord
from discord.ext import commands
from discord import app_commands
from database import Database
from models import User, Faction, Nation, FactionPermission, Rank
from datetime import datetime, timedelta
from pass_generator import PassGenerator
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont
import random

def in_command_channel():
    """Check if command is used in the correct channel"""
    async def predicate(interaction: discord.Interaction) -> bool:
        # Staff and owners can use commands anywhere
        if interaction.user.guild_permissions.administrator:
            return True

        # Check if in command channel
        command_channel_id = bot.command_channels.get(interaction.guild_id)
        return interaction.channel_id == command_channel_id
    return app_commands.check(predicate)

class MegatropoBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        intents.all
        super().__init__(command_prefix="!", intents=intents)
        self.db = Database()
        self.command_channels = {}  # guild_id -> command_channel_id
        self.faction_announcement_channels = {}  # guild_id -> channel_id
        self.nation_announcement_channels = {}  # guild_id -> channel_id

    async def setup_hook(self):
        await self.tree.sync()
        
    async def on_guild_join(self, guild: discord.Guild):
        # Create or get bot role
        bot_role = discord.utils.get(guild.roles, name="MegatroBot")
        if not bot_role:
            try:
                bot_role = await guild.create_role(
                    name="MegatroBot",
                    permissions=discord.Permissions.all(),
                    color=discord.Color.red(),
                    reason="Bot administrative role"
                )
                # Move role position to be high in hierarchy
                positions = {bot_role: len(guild.roles) - 1}  # -1 to be below server owner
                await guild.edit_role_positions(positions)
            except discord.Forbidden:
                print(f"Failed to create bot role in server: {guild.name}")
                return

        # Assign role to bot if not already assigned
        bot_member = guild.get_member(self.user.id)
        if (bot_member and bot_role not in bot_member.roles):
            try:
                await bot_member.add_roles(bot_role, reason="Bot role assignment")
            except discord.Forbidden:
                print(f"Failed to assign bot role in server: {guild.name}")

        # Setup categories and channels
        try:
            await self.setup_categories(guild)
        except discord.Forbidden:
            print(f"Failed to create categories in server: {guild.name}")

    async def on_ready(self):
        print(f'{self.user} has connected to Discord!')
        # Set bot's status to online and add custom status
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Game(name="Managing Factions & Nations")
        )
        
        # Create/assign role in all current servers
        for guild in self.guilds:
            await self.on_guild_join(guild)
        print(f"Bot is active in {len(self.guilds)} servers")

    async def setup_categories(self, guild: discord.Guild):
        # Check if the category already exists
        existing_category = discord.utils.get(guild.categories, name="Bot Management")
        if (existing_category):
            cmd_channel = discord.utils.get(existing_category.text_channels, name="megabot-cmd")
            faction_announce = discord.utils.get(existing_category.text_channels, name="faction-announcements")
            nation_announce = discord.utils.get(existing_category.text_channels, name="nation-announcements")

            if (cmd_channel and faction_announce and nation_announce):
                self.command_channels[guild.id] = cmd_channel.id
                self.faction_announcement_channels[guild.id] = faction_announce.id
                self.nation_announcement_channels[guild.id] = nation_announce.id
                print("The channels already exist.")
                return
            else:
                # Create missing channels inside the existing category
                if (not cmd_channel):
                    cmd_channel = await existing_category.create_text_channel(
                        "megabot-cmd",
                        overwrites={
                            guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                        }
                    )
                    self.command_channels[guild.id] = cmd_channel.id

                if (not faction_announce):
                    faction_announce = await existing_category.create_text_channel(
                        "faction-announcements",
                        overwrites={
                            guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False, add_reactions=True),
                            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                        }
                    )
                    self.faction_announcement_channels[guild.id] = faction_announce.id

                if (not nation_announce):
                    nation_announce = await existing_category.create_text_channel(
                        "nation-announcements",
                        overwrites={
                            guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False, add_reactions=True),
                            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                        }
                    )
                    self.nation_announcement_channels[guild.id] = nation_announce.id

                print("Created missing channels inside the existing category.")
                return

        # Create bot management category
        bot_category = await guild.create_category(
            "Bot Management",
            overwrites={
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
        )
        
        # Create command channel
        cmd_channel = await bot_category.create_text_channel(
            "megabot-cmd",
            overwrites={
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
        )
        self.command_channels[guild.id] = cmd_channel.id

        # Create announcement channels
        faction_announce = await bot_category.create_text_channel(
            "faction-announcements",
            overwrites={
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False, add_reactions=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
        )
        nation_announce = await bot_category.create_text_channel(
            "nation-announcements",
            overwrites={
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False, add_reactions=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
        )
        
        self.faction_announcement_channels[guild.id] = faction_announce.id
        self.nation_announcement_channels[guild.id] = nation_announce.id

    async def can_use_command(self, interaction: discord.Interaction) -> bool:
        """Legacy method - kept for reference but not used"""
        pass

    async def create_faction_category(self, guild: discord.Guild, faction: Faction) -> Optional[discord.CategoryChannel]:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True)
        }
        
        # Get faction members and set permissions
        members = await self.db.get_faction_members(faction.id)
        for member_id in members:
            member = guild.get_member(member_id)
            if member:
                overwrites[member] = discord.PermissionOverwrite(read_messages=True)

        # If faction is part of a nation, add nation members
        if faction.nation_id:
            nation = await self.db.get_nation(faction.nation_id)
            if nation:
                nation_members = await self.db.get_nation_members(nation.id)
                for member_id in nation_members:
                    member = guild.get_member(member_id)
                    if member:
                        overwrites[member] = discord.PermissionOverwrite(read_messages=True)

        try:
            category = await guild.create_category(f"Faction-{faction.name}", overwrites=overwrites)
            await category.create_text_channel("general")
            await category.create_text_channel("announcements")
            return category
        except discord.Forbidden:
            return None

    async def create_nation_category(self, guild: discord.Guild, nation: Nation) -> Optional[discord.CategoryChannel]:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True)
        }
        
        # Get nation members and set permissions
        members = await self.db.get_nation_members(nation.id)
        for member_id in members:
            member = guild.get_member(member_id)
            if member:
                overwrites[member] = discord.PermissionOverwrite(read_messages=True)

        try:
            category = await guild.create_category(f"Nation-{nation.name}", overwrites=overwrites)
            await category.create_text_channel("general")
            await category.create_text_channel("announcements")
            return category
        except discord.Forbidden:
            return None

    async def initialize_user(self, user_id: int) -> bool:
        """Initialize a new user with starting money and default permissions"""
        try:
            await self.db.get_user(user_id)  # This creates the user if they don't exist
            return True
        except Exception as e:
            print(f"Error initializing user {user_id}: {e}")
            return False

    async def initialize_server_structure(self, guild: discord.Guild) -> dict:
        """Initialize all server categories and channels, return status report"""
        status = {
            "success": True,
            "created": [],
            "errors": []
        }
        
        try:
            # Use setup_categories to create or check existing categories and channels
            await self.setup_categories(guild)
            status["created"].append("Bot Management category and channels")

            # Create bot role if it doesn't exist
            bot_role = discord.utils.get(guild.roles, name="MegatroBot")
            if not bot_role:
                bot_role = await guild.create_role(
                    name="MegatroBot",
                    permissions=discord.Permissions.all(),
                    color=discord.Color.red(),
                    reason="Bot administrative role"
                )
                positions = {bot_role: len(guild.roles) - 1}
                await guild.edit_role_positions(positions)
                status["created"].append("MegatroBot role")

            # Ensure images directory exists
            os.makedirs("images", exist_ok=True)
            status["created"].append("images directory")

        except Exception as e:
            status["success"] = False
            status["errors"].append(str(e))

        return status

    def generate_default_icon(self, name: str) -> Image.Image:
        """Generate a default icon with the first letter and a random color"""
        size = (100, 100)
        img = Image.new('RGB', size, color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
        
        # Generate random color
        color = tuple(random.randint(0, 255) for _ in range(3))
        
        # Draw circular vignette
        draw.ellipse([(0, 0), size], fill=color)
        
        # Draw the first letter
        text = name[0].upper()
        text_size = draw.textsize(text, font=font)
        text_position = ((size[0] - text_size[0]) // 2, (size[1] - text_size[1]) // 2)
        draw.text(text_position, text, fill=(255, 255, 255), font=font)
        
        return img

class FactionSelect(discord.ui.Select):
    def __init__(self, factions: List[Faction]):
        options = [
            discord.SelectOption(
                label=faction.name,
                value=str(faction.id),
                description=f"Owner: {faction.owner_id}"
            ) for faction in factions
        ]
        super().__init__(placeholder="Select a faction...", options=options)

    async def callback(self, interaction: discord.Interaction):
        faction_id = int(self.values[0])
        faction = await interaction.client.db.get_faction(faction_id)
        if not faction:
            await interaction.response.send_message("Faction no longer exists!", ephemeral=True)
            return

        members = await interaction.client.db.get_faction_members(faction.id)
        owner = await interaction.client.fetch_user(faction.owner_id)
        
        embed = discord.Embed(title=f"Faction Info - {faction.name}", color=discord.Color.blue())
        embed.add_field(name="ID", value=faction.id)
        embed.add_field(name="Owner", value=owner.name)
        embed.add_field(name="Balance", value=f"${faction.balance}")
        embed.add_field(name="Member Count", value=len(members))
        
        if faction.nation_id:
            nation = await interaction.client.db.get_nation(faction.nation_id)
            embed.add_field(name="Nation", value=nation.name if nation else "None")
        
        if faction.ranks:
            ranks_text = "\n".join([f"{r.name} (Priority: {r.priority})" for r in faction.ranks.values()])
            embed.add_field(name="Ranks", value=ranks_text or "No ranks", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

class FactionSelectView(discord.ui.View):
    def __init__(self, factions: List[Faction]):
        super().__init__()
        self.add_item(FactionSelect(factions))

class NationSelect(discord.ui.Select):
    def __init__(self, nations: List[Nation]):
        options = [
            discord.SelectOption(
                label=nation.name,
                value=str(nation.id),
                description=f"Owner: {nation.owner_id}"
            ) for nation in nations
        ]
        super().__init__(placeholder="Select a nation...", options=options)

    async def callback(self, interaction: discord.Interaction):
        nation_id = int(self.values[0])
        nation = await interaction.client.db.get_nation(nation_id)
        if not nation:
            await interaction.response.send_message("Nation no longer exists!", ephemeral=True)
            return

        owner = await interaction.client.fetch_user(nation.owner_id)
        
        embed = discord.Embed(title=f"Nation Info - {nation.name}", color=discord.Color.gold())
        embed.add_field(name="ID", value=nation.id)
        embed.add_field(name="Owner", value=owner.name)
        embed.add_field(name="Balance", value=f"${nation.balance}")
        
        if nation.allies:
            allies_text = "\n".join([f"• {ally}" for ally in nation.allies])
            embed.add_field(name="Allies", value=allies_text or "No allies", inline=False)

        cursor = interaction.client.db.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM factions WHERE nation_id = ?', (nation.id,))
        faction_count = cursor.fetchone()[0]
        embed.add_field(name="Number of Factions", value=faction_count)

        await interaction.response.send_message(embed=embed, ephemeral=True)

class NationSelectView(discord.ui.View):
    def __init__(self, nations: List[Nation]):
        super().__init__()
        self.add_item(NationSelect(nations))

bot = MegatropoBot()
pass_generator = PassGenerator()

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    await bot.tree.sync()  # Ensure commands are synced
    
@bot.tree.command(name="balance", description="Check your balance")
@in_command_channel()
async def balance(interaction: discord.Interaction):
    user = await bot.db.get_user(interaction.user.id)
    await interaction.response.send_message(f"Your balance: ${user.balance}")

@bot.tree.command(name="create_faction", description="Create a new faction")
@in_command_channel()
async def create_faction(interaction: discord.Interaction, name: str):
    user = await bot.db.get_user(interaction.user.id)
    if user.balance < 500:
        await interaction.response.send_message("You need $500 to create a faction!")
        return
    
    success = await bot.db.create_faction(name, user.id)
    if success:
        await bot.db.modify_balance(user.id, -500)
        await bot.db.create_default_ranks_for_faction(user.id)
        await interaction.response.send_message(f"Faction {name} created successfully!")
    else:
        await interaction.response.send_message("Faction name already exists!")

@bot.tree.command(name="claim_land_request", description="Request to claim land")
@in_command_channel()
async def claim_land_request(interaction: discord.Interaction, name: str, payment_source: str):
    if not any(role.permissions.administrator for role in interaction.user.roles):
        await interaction.response.send_message("You don't have permission to approve land claims!")
        return

    user = await bot.db.get_user(interaction.user.id)
    if payment_source.lower() == "personal":
        if user.balance < 1000:
            await interaction.response.send_message("You need $1000 to claim land!")
            return
        success = await bot.db.create_nation(name, user.id)
        if success:
            await bot.db.modify_balance(user.id, -1000)
            await bot.db.create_default_ranks_for_nation(user.id)
            await interaction.response.send_message(f"Nation {name} created successfully!")
    else:
        faction = await bot.db.get_user_faction(user.id)
        if not faction or faction.balance < 1000:
            await interaction.response.send_message("Your faction needs $1000 to claim land!")
            return
        success = await bot.db.convert_faction_to_nation(faction.id, name)
        if success:
            await bot.db.modify_faction_balance(faction.id, -1000)
            await bot.db.create_default_ranks_for_nation(user.id)
            await interaction.response.send_message(f"Faction converted to nation {name} successfully!")

@bot.tree.command(name="create_nation", description="Create a new nation")
@in_command_channel()
@app_commands.describe(
    name="Name of the new nation",
    type="Type of creation: 'factionconvert' or 'new'",
    payment_source="Payment source: 'personal' or 'faction' (only for 'new' type)"
)
@app_commands.choices(
    type=[
        app_commands.Choice(name="Faction Convert", value="factionconvert"),
        app_commands.Choice(name="New", value="new")
    ],
    payment_source=[
        app_commands.Choice(name="Personal", value="personal"),
        app_commands.Choice(name="Faction", value="faction")
    ]
)
async def create_nation(interaction: discord.Interaction, name: str, type: str, payment_source: Optional[str] = None):
    user = await bot.db.get_user(interaction.user.id)
    
    if type.lower() == "factionconvert":
        faction = await bot.db.get_user_faction(user.id)
        if not faction or faction.balance < 1000:
            await interaction.response.send_message("Your faction needs $1000 to convert to a nation!")
            return
        success = await bot.db.convert_faction_to_nation(faction.id, name)
        if success:
            await bot.db.modify_faction_balance(faction.id, -1000)
            await bot.db.create_default_ranks_for_nation(user.id)
            await interaction.response.send_message(f"Faction converted to nation {name} successfully!")
        else:
            await interaction.response.send_message("Failed to convert faction to nation!")
    elif type.lower() == "new":
        if payment_source.lower() == "personal":
            if user.balance < 1000:
                await interaction.response.send_message("You need $1000 to create a nation!")
                return
            success = await bot.db.create_nation(name, user.id)
            if success:
                await bot.db.modify_balance(user.id, -1000)
                await bot.db.create_default_ranks_for_nation(user.id)
                await interaction.response.send_message(f"Nation {name} created successfully!")
            else:
                await interaction.response.send_message("Failed to create nation!")
        elif payment_source.lower() == "faction":
            faction = await bot.db.get_user_faction(user.id)
            if not faction or faction.balance < 1000:
                await interaction.response.send_message("Your faction needs $1000 to create a nation!")
                return
            success = await bot.db.create_nation(name, user.id)
            if success:
                await bot.db.modify_faction_balance(faction.id, -1000)
                await bot.db.create_default_ranks_for_nation(user.id)
                await interaction.response.send_message(f"Nation {name} created successfully!")
            else:
                await interaction.response.send_message("Failed to create nation!")
        else:
            await interaction.response.send_message("Invalid payment source! Use 'personal' or 'faction'.")
    else:
        await interaction.response.send_message("Invalid type! Use 'factionconvert' or 'new'.")

@bot.tree.command(name="create-rank", description="Create a new rank in your faction or nation")
@in_command_channel()
@app_commands.describe(
    entity_type="Type of entity: 'faction' or 'nation'",
    name="Name of the new rank",
    priority="Priority of the new rank",
    manage_money="Permission to manage money",
    manage_members="Permission to manage members",
    manage_ranks="Permission to manage ranks",
    manage_alliances="Permission to manage alliances"
)
@app_commands.choices(
    entity_type=[
        app_commands.Choice(name="Faction", value="faction"),
        app_commands.Choice(name="Nation", value="nation")
    ]
)
async def create_rank(
    interaction: discord.Interaction,
    entity_type: str,
    name: str,
    priority: int,
    manage_money: bool = False,
    manage_members: bool = False,
    manage_ranks: bool = False,
    manage_alliances: bool = False
):
    await interaction.response.defer()  # Defer the interaction at the beginning
    user = await bot.db.get_user(interaction.user.id)
    
    if entity_type == "faction":
        entity = await bot.db.get_user_faction(user.id)
        if not entity:
            await interaction.followup.send("You're not in a faction!")
            return
        user_rank = await bot.db.get_faction_member_rank(entity.id, user.id)
    elif entity_type == "nation":
        entity = await bot.db.get_nation(user.nation_id)
        if not entity:
            await interaction.followup.send("You're not in a nation!")
            return
        user_rank = await bot.db.get_faction_member_rank(entity.id, user.id)
    else:
        await interaction.followup.send("Invalid entity type! Use 'faction' or 'nation'.")
        return

    if not user_rank or user_rank.priority > 0:
        await interaction.followup.send("You don't have permission to create ranks!")
        return

    permissions = set()
    if manage_money: permissions.add(FactionPermission.MANAGE_MONEY)
    if manage_members: permissions.add(FactionPermission.ADD_MEMBERS)
    if manage_ranks: permissions.add(FactionPermission.MANAGE_RANKS)
    if manage_alliances: permissions.add(FactionPermission.MANAGE_ALLIANCES)

    rank_id = await bot.db.create_rank(entity.id, name, priority, [p.name for p in permissions])
    if rank_id:
        await interaction.followup.send(f"Rank {name} created successfully!")
    else:
        await interaction.followup.send("Failed to create rank!")

@bot.tree.command(name="remove-rank", description="Remove a rank from your faction or nation")
@in_command_channel()
@app_commands.describe(
    entity_type="Type of entity: 'faction' or 'nation'",
    rank_name="Name of the rank to remove"
)
async def remove_rank(interaction: discord.Interaction, entity_type: str, rank_name: str):
    await interaction.response.defer()  # Defer the interaction at the beginning
    user = await bot.db.get_user(interaction.user.id)
    
    if entity_type.lower() == "faction":
        entity = await bot.db.get_user_faction(user.id)
        if not entity:
            await interaction.followup.send("You're not in a faction!")
            return
        user_rank = await bot.db.get_faction_member_rank(entity.id, user.id)
    elif entity_type.lower() == "nation":
        entity = await bot.db.get_nation(user.nation_id)
        if not entity:
            await interaction.followup.send("You're not in a nation!")
            return
        user_rank = await bot.db.get_faction_member_rank(entity.id, user.id)
    else:
        await interaction.followup.send("Invalid entity type! Use 'faction' or 'nation'.")
        return

    if not user_rank or user_rank.priority > 0:
        await interaction.followup.send("You don't have permission to remove ranks!")
        return

    success = await bot.db.remove_rank(entity.id, rank_name)
    if success:
        await interaction.followup.send(f"Rank {rank_name} removed successfully!")
    else:
        await interaction.followup.send("Failed to remove rank!")

@bot.tree.command(name="edit-rank", description="Edit a rank in your faction or nation")
@in_command_channel()
@app_commands.describe(
    entity_type="Type of entity: 'faction' or 'nation'",
    rank_name="Name of the rank to edit",
    new_name="New name of the rank",
    new_priority="New priority of the rank",
    manage_money="Permission to manage money",
    manage_members="Permission to manage members",
    manage_ranks="Permission to manage ranks",
    manage_alliances="Permission to manage alliances"
)
async def edit_rank(
    interaction: discord.Interaction,
    entity_type: str,
    rank_name: str,
    new_name: Optional[str] = None,
    new_priority: Optional[int] = None,
    manage_money: Optional[bool] = None,
    manage_members: Optional[bool] = None,
    manage_ranks: Optional[bool] = None,
    manage_alliances: Optional[bool] = None
):
    await interaction.response.defer()  # Defer the interaction at the beginning
    user = await bot.db.get_user(interaction.user.id)
    
    if entity_type.lower() == "faction":
        entity = await bot.db.get_user_faction(user.id)
        if not entity:
            await interaction.followup.send("You're not in a faction!")
            return
        user_rank = await bot.db.get_faction_member_rank(entity.id, user.id)
    elif entity_type.lower() == "nation":
        entity = await bot.db.get_nation(user.nation_id)
        if not entity:
            await interaction.followup.send("You're not in a nation!")
            return
        user_rank = await bot.db.get_faction_member_rank(entity.id, user.id)
    else:
        await interaction.followup.send("Invalid entity type! Use 'faction' or 'nation'.")
        return

    if not user_rank or user_rank.priority > 0:
        await interaction.followup.send("You don't have permission to edit ranks!")
        return

    permissions = set()
    if manage_money is not None: permissions.add(FactionPermission.MANAGE_MONEY)
    if manage_members is not None: permissions.add(FactionPermission.ADD_MEMBERS)
    if manage_ranks is not None: permissions.add(FactionPermission.MANAGE_RANKS)
    if manage_alliances is not None: permissions.add(FactionPermission.MANAGE_ALLIANCES)

    success = await bot.db.edit_rank(entity.id, rank_name, new_name, new_priority, [p.name for p in permissions])
    if success:
        await interaction.followup.send(f"Rank {rank_name} edited successfully!")
    else:
        await interaction.followup.send("Failed to edit rank!")

@bot.tree.command(name="disband", description="Disband your faction or nation")
@in_command_channel()
@app_commands.describe(
    entity_type="Type of entity: 'faction' or 'nation'"
)
async def disband(interaction: discord.Interaction, entity_type: str):
    await interaction.response.defer()  # Defer the interaction at the beginning
    user = await bot.db.get_user(interaction.user.id)
    
    if entity_type.lower() == "faction":
        entity = await bot.db.get_user_faction(user.id)
        if not entity:
            await interaction.followup.send("You're not in a faction!")
            return
        if entity.owner_id != user.id:
            await interaction.followup.send("Only the faction owner can disband the faction!")
            return
    elif entity_type.lower() == "nation":
        entity = await bot.db.get_nation(user.nation_id)
        if not entity:
            await interaction.followup.send("You're not in a nation!")
            return
        if entity.owner_id != user.id:
            await interaction.followup.send("Only the nation leader can disband the nation!")
            return
    else:
        await interaction.followup.send("Invalid entity type! Use 'faction' or 'nation'.")
        return

    # Generate a random number for confirmation
    import random
    confirmation_number = random.randint(1000, 9999)
    await interaction.followup.send(f"To confirm disbanding the {entity_type}, please type the following number: {confirmation_number}")

    try:
        message = await bot.wait_for(
            'message',
            timeout=60.0,
            check=lambda m: m.author.id == interaction.user.id and m.channel.id == interaction.channel.id
        )
        if message.content == str(confirmation_number):
            if entity_type.lower() == "faction":
                success = await bot.db.disband_faction(entity.id)
            else:
                success = await bot.db.disband_nation(entity.id)
            
            if success:
                await interaction.followup.send(f"{entity_type.capitalize()} disbanded successfully!")
            else:
                await interaction.followup.send(f"Failed to disband {entity_type}!")
        else:
            await interaction.followup.send("Disbanding cancelled. Incorrect confirmation number.")
    except TimeoutError:
        await interaction.followup.send("Disbanding cancelled. Confirmation timed out.")

@bot.tree.command(name="add-member", description="Add a member to your faction or nation")
@in_command_channel()
@app_commands.describe(
    entity_type="Type of entity: 'faction' or 'nation'",
    user="Optional: Directly mention a user to invite"
)
@app_commands.choices(
    entity_type=[
        app_commands.Choice(name="Faction", value="faction"),
        app_commands.Choice(name="Nation", value="nation")
    ]
)
async def add_member(interaction: discord.Interaction, entity_type: str, user: discord.User = None):
    inviter = await bot.db.get_user(interaction.user.id)
    
    if entity_type == "faction":
        entity = await bot.db.get_user_faction(inviter.id)
        if not entity:
            await interaction.response.send_message("You're not in a faction!")
            return
        rank = await bot.db.get_faction_member_rank(entity.id, inviter.id)
    elif entity_type == "nation":
        entity = await bot.db.get_nation(inviter.nation_id)
        if not entity:
            await interaction.response.send_message("You're not in a nation!")
            return
        rank = await bot.db.get_faction_member_rank(entity.id, inviter.id)
    else:
        await interaction.response.send_message("Invalid entity type! Use 'faction' or 'nation'.")
        return

    if not rank or FactionPermission.ADD_MEMBERS not in rank.permissions:
        await interaction.response.send_message("You don't have permission to add members!")
        return

    if user:
        success = await bot.db.add_pending_invite(user.id, entity.id)
        if success:
            await interaction.response.send_message(
                f"Invited {user.mention} to {entity.name}! They can accept with `/accept-invite {entity_type} {entity.id}`"
            )
    else:
        await interaction.response.send_message("Please mention the users to invite in your next message:")
        try:
            message = await bot.wait_for(
                'message',
                timeout=30.0,
                check=lambda m: m.author.id == interaction.user.id and m.channel.id == interaction.channel.id
            )
            mentions = message.mentions
            if not mentions:
                await interaction.followup.send("No users mentioned!")
                return

            for mentioned_user in mentions:
                await bot.db.add_pending_invite(mentioned_user.id, entity.id)
            
            await interaction.followup.send(
                f"Invited {len(mentions)} users to {entity.name}! They can accept with `/accept-invite {entity_type} {entity.id}`"
            )
        except TimeoutError:
            await interaction.followup.send("Timed out waiting for mentions!")

@bot.tree.command(name="accept-invite", description="Accept an invite to a faction or nation")
@in_command_channel()
@app_commands.describe(
    entity_type="Type of entity: 'faction' or 'nation'",
    entity_id="ID of the faction or nation"
)
@app_commands.choices(
    entity_type=[
        app_commands.Choice(name="Faction", value="faction"),
        app_commands.Choice(name="Nation", value="nation")
    ]
)
async def accept_invite(interaction: discord.Interaction, entity_type: str, entity_id: int):
    user = await bot.db.get_user(interaction.user.id)
    
    if entity_type == "faction":
        success = await bot.db.accept_faction_invite(user.id, entity_id)
    elif entity_type == "nation":
        success = await bot.db.accept_nation_invite(user.id, entity_id)
    else:
        await interaction.response.send_message("Invalid entity type! Use 'faction' or 'nation'.")
        return

    if success:
        await interaction.response.send_message(f"Successfully joined the {entity_type}!")
    else:
        await interaction.response.send_message(f"Failed to join the {entity_type}. Make sure you have a pending invite.")

@bot.tree.command(name="user-info", description="Get information about a user")
@in_command_channel()
async def user_info(interaction: discord.Interaction, user: discord.User = None):
    await interaction.response.defer()  # Defer the interaction at the beginning
    target_user = user or interaction.user
    user_data = await bot.db.get_user(target_user.id)
    faction = await bot.db.get_user_faction(target_user.id)
    
    embed = discord.Embed(title=f"User Info - {target_user.name}")
    embed.add_field(name="ID", value=target_user.id)
    embed.add_field(name="Balance", value=f"${user_data.balance}")
    embed.add_field(name="Faction", value=faction.name if faction else "None")
    
    await interaction.followup.send(embed=embed)  # Use followup to send the message

@bot.tree.command(name="faction-info", description="Get information about a faction")
@in_command_channel()
async def faction_info(interaction: discord.Interaction):
    await interaction.response.defer()  # Defer the interaction at the beginning
    
    # Get all factions
    cursor = bot.db.conn.cursor()
    cursor.execute('SELECT id FROM factions')
    faction_ids = [row[0] for row in cursor.fetchall()]
    
    if not faction_ids:
        await interaction.followup.send("No factions exist yet!")
        return
        
    factions = []
    for fid in faction_ids:
        faction = await bot.db.get_faction(fid)
        if faction:
            factions.append(faction)
    
    view = FactionSelectView(factions)
    await interaction.followup.send("Select a faction to view:", view=view)

@bot.tree.command(name="nation-info", description="Get information about a nation")
@in_command_channel()
async def nation_info(interaction: discord.Interaction):
    await interaction.response.defer()
    
    # Get all nations
    cursor = bot.db.conn.cursor()
    cursor.execute('SELECT id FROM nations')
    nation_ids = [row[0] for row in cursor.fetchall()]
    
    if not nation_ids:
        await interaction.followup.send("No nations exist yet!")
        return
        
    nations = []
    for nid in nation_ids:
        nation = await bot.db.get_nation(nid)
        if nation:
            nations.append(nation)
    
    view = NationSelectView(nations)
    await interaction.followup.send("Select a nation to view:", view=view)

@bot.tree.command(name="form-alliance", description="Form an alliance with another nation")
@in_command_channel()
async def form_alliance(interaction: discord.Interaction, nation_name: str):
    user = await bot.db.get_user(interaction.user.id)
    if not user.nation_id:
        await interaction.response.send_message("You must be a nation leader to form alliances!")
        return

    user_nation = await bot.db.get_nation(user.nation_id)
    if user_nation.owner_id != user.id:
        await interaction.response.send_message("Only nation leaders can form alliances!")
        return

    target_nation = await bot.db.get_nation_by_name(nation_name)
    if not target_nation:
        await interaction.response.send_message(f"Nation '{nation_name}' not found!")
        return

    if target_nation.id == user_nation.id:
        await interaction.response.send_message("You cannot form an alliance with your own nation!")
        return

    success = await bot.db.add_alliance(user_nation.id, target_nation.id)
    if success:
        await interaction.response.send_message(f"Alliance formed between {user_nation.name} and {target_nation.name}!")
    else:
        await interaction.response.send_message("Failed to form alliance!")

@bot.tree.command(name="break-alliance", description="Break an alliance with another nation")
@in_command_channel()
async def break_alliance(interaction: discord.Interaction, nation_name: str):
    user = await bot.db.get_user(interaction.user.id)
    if not user.nation_id:
        await interaction.response.send_message("You must be a nation leader to break alliances!")
        return

    user_nation = await bot.db.get_nation(user.nation_id)
    if user_nation.owner_id != user.id:
        await interaction.response.send_message("Only nation leaders can break alliances!")
        return

    target_nation = await bot.db.get_nation_by_name(nation_name)
    if not target_nation:
        await interaction.response.send_message(f"Nation '{nation_name}' not found!")
        return

    success = await bot.db.remove_alliance(user_nation.id, target_nation.id)
    if success:
        await interaction.response.send_message(f"Alliance between {user_nation.name} and {target_nation.name} has been broken!")
    else:
        await interaction.response.send_message("Failed to break alliance!")

@bot.tree.command(name="transfer", description="Transfer money between faction/nation pools")
@in_command_channel()
async def transfer_money(
    interaction: discord.Interaction,
    amount: float,
    to_type: str,
    to_name: str
):
    if amount <= 0:
        await interaction.response.send_message("Amount must be positive!")
        return

    user = await bot.db.get_user(interaction.user.id)
    user_faction = await bot.db.get_user_faction(user.id)
    user_nation = await bot.db.get_nation(user.nation_id) if user.nation_id else None

    # Determine source of funds
    from_type = None
    from_id = None
    if user_faction and await bot.db.get_faction_member_rank(user_faction.id, user.id):
        from_type = 'faction'
        from_id = user_faction.id
    elif user_nation and user_nation.owner_id == user.id:
        from_type = 'nation'
        from_id = user_nation.id
    
    if not from_type:
        await interaction.response.send_message("You don't have permission to transfer money!")
        return

    # Determine destination
    to_id = None
    if to_type.lower() == 'faction':
        target = await bot.db.get_faction_by_name(to_name)
        if target:
            to_id = target.id
    elif to_type.lower() == 'nation':
        target = await bot.db.get_nation_by_name(to_name)
        if target:
            to_id = target.id
    
    if not to_id:
        await interaction.response.send_message(f"{to_type.capitalize()} '{to_name}' not found!")
        return

    success = await bot.db.transfer_money(from_type, from_id, to_type.lower(), to_id, amount)
    if success:
        await interaction.response.send_message(
            f"Successfully transferred ${amount} from your {from_type} to {to_name}!"
        )
    else:
        await interaction.response.send_message("Transfer failed! Insufficient funds or invalid transfer.")

@bot.tree.command(name="grant-pass", description="Grant a pass to a user")
@in_command_channel()
async def grant_pass(interaction: discord.Interaction, user: discord.User, days: int = 30):
    granter = await bot.db.get_user(interaction.user.id)
    faction = await bot.db.get_user_faction(granter.id)
    
    if not faction or faction.owner_id != granter.id:
        await interaction.response.send_message("Only faction owners can grant passes!")
        return

    expiry_date = datetime.now() + timedelta(days=days)
    user_pass = await bot.db.create_user_pass(user.id, expiry_date)
    if user_pass:
        pass_image = pass_generator.create_pass_image(user_pass, user.name)
        pass_image.save(f"temp_pass_{user.id}.png")
        
        await interaction.response.send_message(
            f"Pass created for {user.name}",
            file=discord.File(f"temp_pass_{user.id}.png")
        )
        os.remove(f"temp_pass_{user.id}.png")
    else:
        await interaction.response.send_message("Failed to create pass!")

@bot.tree.command(name="request-pass", description="Request a new pass (costs 5 if no faction/nation)")
@in_command_channel()
async def request_pass(interaction: discord.Interaction):
    await interaction.response.defer()  # Add this line
    
    user = await bot.db.get_user(interaction.user.id)
    
    if not user.faction_id and not user.nation_id:
        if user.balance < 5:
            await interaction.followup.send("You need $5 to request a pass!")
            return
        await bot.db.modify_balance(user.id, -5)

    expiry_date = datetime.now() + timedelta(days=30)
    user_pass = await bot.db.create_user_pass(user.id, expiry_date)
    if user_pass:
        pass_image = pass_generator.create_pass_image(user_pass, interaction.user.name)
        pass_image.save(f"temp_pass_{user.id}.png")
        
        await interaction.followup.send(
            f"Pass created successfully!",
            file=discord.File(f"temp_pass_{user.id}.png")
        )
        os.remove(f"temp_pass_{user.id}.png")
    else:
        await interaction.followup.send("Failed to create pass!")

@bot.tree.command(name="show-pass", description="Show your pass")
@in_command_channel()
async def show_pass(interaction: discord.Interaction):
    user = await bot.db.get_user(interaction.user.id)
    user_pass = await bot.db.get_user_pass(user.id)
    
    if not user_pass:
        await interaction.response.send_message("You don't have a valid pass!")
        return

    pass_image = pass_generator.create_pass_image(user_pass, interaction.user.name)
    pass_image.save(f"temp_pass_{user.id}.png")
    
    await interaction.response.send_message(
        "Here's your pass:",
        file=discord.File(f"temp_pass_{user.id}.png")
    )
    os.remove(f"temp_pass_{user.id}.png")

@bot.tree.command(name="upload-faction-icon", description="Upload your faction's icon")
@in_command_channel()
async def upload_faction_icon(interaction: discord.Interaction):
    user = await bot.db.get_user(interaction.user.id)
    faction = await bot.db.get_user_faction(user.id)
    
    if not faction or faction.owner_id != user.id:
        await interaction.response.send_message("You must be a faction owner to upload an icon!")
        return

    await interaction.response.send_message("Please upload your faction icon (PNG format).")
    
    try:
        message = await bot.wait_for(
            'message',
            timeout=60.0,
            check=lambda m: m.author.id == interaction.user.id and interaction.channel.id == m.channel.id and m.attachments
        )
        
        if not message.attachments or not message.attachments[0].filename.lower().endswith('.png'):
            await interaction.followup.send("Please upload a PNG image!")
            return

        icon_data = await message.attachments[0].read()
        success = await bot.db.store_entity_image('faction', faction.id, icon_data)
        
        if success:
            await interaction.followup.send("Faction icon updated successfully!")
        else:
            await interaction.followup.send("Failed to update faction icon!")
            
    except TimeoutError:
        await interaction.followup.send("Timed out waiting for icon upload!")

@bot.tree.command(name="upload-nation-icon", description="Upload your nation's icon")
@in_command_channel()
async def upload_nation_icon(interaction: discord.Interaction):
    user = await bot.db.get_user(interaction.user.id)
    nation = await bot.db.get_nation(user.nation_id) if user.nation_id else None
    
    if not nation or nation.owner_id != user.id:
        await interaction.response.send_message("You must be a nation leader to upload an icon!")
        return

    await interaction.response.send_message("Please upload your nation icon (PNG format).")
    
    try:
        message = await bot.wait_for(
            'message',
            timeout=60.0,
            check=lambda m: m.author.id == interaction.user.id and interaction.channel.id == m.channel.id and m.attachments
        )
        
        if not message.attachments or not message.attachments[0].filename.lower().endswith('.png'):
            await interaction.followup.send("Please upload a PNG image!")
            return

        icon_data = await message.attachments[0].read()
        success = await bot.db.store_entity_image('nation', nation.id, icon_data)
        
        if success:
            await interaction.followup.send("Nation icon updated successfully!")
        else:
            await interaction.followup.send("Failed to update nation icon!")
            
    except TimeoutError:
        await interaction.followup.send("Timed out waiting for icon upload!")

@bot.tree.command(name="verify-pass", description="Verify another user's pass")
@in_command_channel()
async def verify_pass(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer()  # Add this to prevent timeout
    
    verifier = await bot.db.get_user(interaction.user.id)
    target = await bot.db.get_user(user.id)
    
    if not (verifier.faction_id or verifier.nation_id):
        await interaction.followup.send("You must be part of a faction or nation to verify passes!")
        return

    if not (target.faction_id or target.nation_id):
        user_pass = await bot.db.get_user_pass(user.id)
        if not user_pass:
            await interaction.followup.send("User has no valid pass!")
            return
            
        await interaction.followup.send(f"Requesting pass from {user.mention}. They should use /show-pass to display it.")
        return

    await interaction.followup.send(
        f"Requesting pass from {user.mention}. They should use /show-pass to display it.\n"
        "Once they show their pass, use /check-pass to verify it."
    )

@bot.tree.command(name="check-pass", description="Check a displayed pass")
@in_command_channel()
@app_commands.describe(
    pass_file="The pass image file to verify",
    user="The user whose pass to verify"
)
async def check_pass(
    interaction: discord.Interaction, 
    pass_file: discord.Attachment,
    user: discord.User
):
    if not pass_file.filename.lower().endswith('.png'):
        await interaction.response.send_message("Invalid file format! Please upload a PNG image.")
        return

    # Save temporarily and verify
    temp_path = f"temp_verify_{interaction.id}.png"
    await pass_file.save(temp_path)
    
    user_pass = await bot.db.get_user_pass(user.id)
    if not user_pass:
        await interaction.response.send_message(f"No pass data found for {user.name}!")
        os.remove(temp_path)
        return

    is_valid, discrepancies, marked_image = pass_generator.verify_pass_image(temp_path, user_pass)
    os.remove(temp_path)

    if is_valid:
        await interaction.response.send_message(f"✅ Pass verification successful for {user.name}!")
    else:
        marked_path = f"marked_pass_{interaction.id}.png"
        marked_image.save(marked_path)
        await interaction.response.send_message(
            f"❌ Pass verification failed for {user.name}!\nDiscrepancies found:\n" + 
            "\n".join(f"- {d}" for d in discrepancies),
            file=discord.File(marked_path)
        )
        os.remove(marked_path)

@bot.tree.command(name="announce", description="Make an announcement")
@in_command_channel()
async def announce(
    interaction: discord.Interaction,
    nation: bool,
    faction: bool,
    text: str
):
    # Check permissions
    user = await bot.db.get_user(interaction.user.id)
    can_announce_faction = False
    can_announce_nation = False
    
    if faction:
        user_faction = await bot.db.get_user_faction(user.id)
        if user_faction:
            rank = await bot.db.get_faction_member_rank(user_faction.id, user.id)
            can_announce_faction = user_faction.owner_id == user.id or (rank and FactionPermission.MANAGE_ANNOUNCEMENTS in rank.permissions)

    if nation:
        user_nation = await bot.db.get_nation(user.nation_id) if user.nation_id else None
        if user_nation:
            can_announce_nation = user_nation.owner_id == user.id

    if not (can_announce_faction or can_announce_nation):
        await interaction.response.send_message("You don't have permission to make announcements!")
        return

    # Create announcement embed
    embed = discord.Embed(
        title="Announcement",
        description=text,
        color=discord.Color.blue() if faction else discord.Color.gold()
    )
    
    if faction and can_announce_faction:
        embed.set_author(name=user_faction.name)
        if os.path.exists(f"images/faction_{user_faction.id}.png"):
            embed.set_thumbnail(url=f"attachment://faction_icon.png")
        
        channel = interaction.guild.get_channel(bot.faction_announcement_channels[interaction.guild_id])
        await channel.send(embed=embed)

    if nation and can_announce_nation:
        embed.set_author(name=user_nation.name)
        if os.path.exists(f"images/nation_{user_nation.id}.png"):
            embed.set_thumbnail(url=f"attachment://nation_icon.png")
        
        channel = interaction.guild.get_channel(bot.nation_announcement_channels[interaction.guild_id])
        await channel.send(embed=embed)

    await interaction.response.send_message("Announcement(s) sent successfully!")

@bot.tree.command(name="setup", description="Initialize bot setup for the server")
@in_command_channel()
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    """Initialize server structure and user data"""
    await interaction.response.defer()

    # Initialize server structure
    status = await bot.initialize_server_structure(interaction.guild)
    
    # Initialize all users
    member_status = []
    for member in interaction.guild.members:
        if not member.bot:
            success = await bot.initialize_user(member.id)
            member_status.append(f"{'✅' if success else '❌'} {member.name}")

    # Refresh commands
    await bot.tree.sync()

    # Create response embed
    embed = discord.Embed(
        title="Server Setup Status",
        color=discord.Color.green() if status["success"] else discord.Color.red()
    )

    # Add server structure status
    if status["created"]:
        embed.add_field(
            name="Created Successfully",
            value="\n".join(f"✅ {item}" for item in status["created"]),
            inline=False
        )

    if status["errors"]:
        embed.add_field(
            name="Errors",
            value="\n".join(f"❌ {error}" for error in status["errors"]),
            inline=False
        )

    # Add user initialization status
    embed.add_field(
        name="User Initialization",
        value="\n".join(member_status[:25]) + (
            f"\n...and {len(member_status) - 25} more" if len(member_status) > 25 else ""
        ),
        inline=False
    )

    await interaction.followup.send(embed=embed)

# Get token from environment variable
TOKEN = os.getenv('DCBOTTOKEN')
if not TOKEN:
    raise ValueError("No bot token found! Set the DCBOTTOKEN environment variable.")

bot.run(TOKEN)
