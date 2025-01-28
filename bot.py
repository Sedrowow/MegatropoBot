import os
import discord
from discord.ext import commands
from discord import app_commands
from database import Database
from models import User, Faction, Nation, FactionPermission
from datetime import datetime, timedelta
from pass_generator import PassGenerator

class MegatropoBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        intents.all
        super().__init__(command_prefix="!", intents=intents)
        self.db = Database()

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
                    color=discord.Color.blue(),
                    reason="Bot administrative role"
                )
                # Move role position to be high in hierarchy
                positions = {bot_role: len(guild.roles) - 2}  # -1 to be below server owner
                await guild.edit_role_positions(positions)
            except discord.Forbidden:
                print(f"Failed to create bot role in {guild.name}")
                return

        # Assign role to bot if not already assigned
        bot_member = guild.get_member(self.user.id)
        if bot_member and bot_role not in bot_member.roles:
            try:
                await bot_member.add_roles(bot_role, reason="Bot role assignment")
            except discord.Forbidden:
                print(f"Failed to assign bot role in {guild.name}")

    async def on_ready(self):
        print(f'{self.user} has connected to Discord!')
        # Set bot's status to online and add custom status
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Game(name="Managing Factions & Nations")
        )
        
        # Create/assign role in all current guilds
        for guild in self.guilds:
            await self.on_guild_join(guild)

bot = MegatropoBot()
pass_generator = PassGenerator()

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    
@bot.tree.command(name="balance", description="Check your balance")
async def balance(interaction: discord.Interaction):
    user = await bot.db.get_user(interaction.user.id)
    await interaction.response.send_message(f"Your balance: ${user.balance}")

@bot.tree.command(name="create_faction", description="Create a new faction")
async def create_faction(interaction: discord.Interaction, name: str):
    user = await bot.db.get_user(interaction.user.id)
    if user.balance < 500:
        await interaction.response.send_message("You need $500 to create a faction!")
        return
    
    success = await bot.db.create_faction(name, user.id)
    if success:
        await bot.db.modify_balance(user.id, -500)
        await interaction.response.send_message(f"Faction {name} created successfully!")
    else:
        await interaction.response.send_message("Faction name already exists!")

@bot.tree.command(name="claim_land", description="Request to claim land")
async def claim_land(interaction: discord.Interaction, name: str, payment_source: str):
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
            await interaction.response.send_message(f"Nation {name} created successfully!")
    else:
        faction = await bot.db.get_user_faction(user.id)
        if not faction or faction.balance < 1000:
            await interaction.response.send_message("Your faction needs $1000 to claim land!")
            return
        success = await bot.db.convert_faction_to_nation(faction.id, name)
        if success:
            await bot.db.modify_faction_balance(faction.id, -1000)
            await interaction.response.send_message(f"Faction converted to nation {name} successfully!")

@bot.tree.command(name="create-rank", description="Create a new rank in your faction")
async def create_rank(
    interaction: discord.Interaction,
    name: str,
    priority: int,
    manage_money: bool = False,
    manage_members: bool = False,
    manage_ranks: bool = False,
    manage_alliances: bool = False
):
    user = await bot.db.get_user(interaction.user.id)
    faction = await bot.db.get_user_faction(user.id)
    if not faction:
        await interaction.response.send_message("You're not in a faction!")
        return

    user_rank = await bot.db.get_faction_member_rank(faction.id, user.id)
    if not user_rank or user_rank.priority > 0:
        await interaction.response.send_message("You don't have permission to create ranks!")
        return

    permissions = set()
    if manage_money: permissions.add(FactionPermission.MANAGE_MONEY)
    if manage_members: permissions.add(FactionPermission.ADD_MEMBERS)
    if manage_ranks: permissions.add(FactionPermission.MANAGE_RANKS)
    if manage_alliances: permissions.add(FactionPermission.MANAGE_ALLIANCES)

    rank_id = await bot.db.create_rank(faction.id, name, priority, [p.name for p in permissions])
    if rank_id:
        await interaction.response.send_message(f"Rank {name} created successfully!")
    else:
        await interaction.response.send_message("Failed to create rank!")

@bot.tree.command(name="add-member", description="Add a member to your faction")
@app_commands.describe(user="Optional: Directly mention a user to invite")
async def add_member(interaction: discord.Interaction, user: discord.User = None):
    inviter = await bot.db.get_user(interaction.user.id)
    faction = await bot.db.get_user_faction(inviter.id)
    if not faction:
        await interaction.response.send_message("You're not in a faction!")
        return

    rank = await bot.db.get_faction_member_rank(faction.id, inviter.id)
    if not rank or FactionPermission.ADD_MEMBERS not in rank.permissions:
        await interaction.response.send_message("You don't have permission to add members!")
        return

    if user:
        success = await bot.db.add_pending_invite(user.id, faction.id)
        if success:
            await interaction.response.send_message(
                f"Invited {user.mention} to {faction.name}! They can accept with `/accept-invite {faction.name}`"
            )
    else:
        await interaction.response.send_message("Please mention the users to invite in your next message:")
        try:
            message = await bot.wait_for(
                'message',
                timeout=30.0,
                check=lambda m: m.author == interaction.user and m.channel == interaction.channel
            )
            mentions = message.mentions
            if not mentions:
                await interaction.followup.send("No users mentioned!")
                return

            for mentioned_user in mentions:
                await bot.db.add_pending_invite(mentioned_user.id, faction.id)
            
            await interaction.followup.send(
                f"Invited {len(mentions)} users to {faction.name}! They can accept with `/accept-invite {faction.name}`"
            )
        except TimeoutError:
            await interaction.followup.send("Timed out waiting for mentions!")

@bot.tree.command(name="user-info", description="Get information about a user")
async def user_info(interaction: discord.Interaction, user: discord.User = None):
    target_user = user or interaction.user
    user_data = await bot.db.get_user(target_user.id)
    faction = await bot.db.get_user_faction(target_user.id)
    
    embed = discord.Embed(title=f"User Info - {target_user.name}")
    embed.add_field(name="ID", value=target_user.id)
    embed.add_field(name="Balance", value=f"${user_data.balance}")
    embed.add_field(name="Faction", value=faction.name if faction else "None")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="faction-info", description="Get information about a faction")
async def faction_info(interaction: discord.Interaction, name: str = None):
    if name:
        faction = await bot.db.get_faction_by_name(name)
    else:
        user = await bot.db.get_user(interaction.user.id)
        faction = await bot.db.get_user_faction(user.id)

    if not faction:
        await interaction.response.send_message("Faction not found!")
        return

    members = await bot.db.get_faction_members(faction.id)
    owner = await bot.client.fetch_user(faction.owner_id)
    
    embed = discord.Embed(title=f"Faction Info - {faction.name}", color=discord.Color.blue())
    embed.add_field(name="ID", value=faction.id)
    embed.add_field(name="Owner", value=owner.name)
    embed.add_field(name="Balance", value=f"${faction.balance}")
    embed.add_field(name="Member Count", value=len(members))
    
    if faction.nation_id:
        nation = await bot.db.get_nation(faction.nation_id)
        embed.add_field(name="Nation", value=nation.name if nation else "None")
    
    if faction.ranks:
        ranks_text = "\n".join([f"{r.name} (Priority: {r.priority})" for r in faction.ranks.values()])
        embed.add_field(name="Ranks", value=ranks_text or "No ranks", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="nation-info", description="Get information about a nation")
async def nation_info(interaction: discord.Interaction, name: str = None):
    if name:
        nation = await bot.db.get_nation_by_name(name)
    else:
        user = await bot.db.get_user(interaction.user.id)
        if user.nation_id:
            nation = await bot.db.get_nation(user.nation_id)
        else:
            await interaction.response.send_message("You're not in a nation!")
            return

    if not nation:
        await interaction.response.send_message("Nation not found!")
        return

    owner = await bot.client.fetch_user(nation.owner_id)
    
    embed = discord.Embed(title=f"Nation Info - {nation.name}", color=discord.Color.gold())
    embed.add_field(name="ID", value=nation.id)
    embed.add_field(name="Owner", value=owner.name)
    embed.add_field(name="Balance", value=f"${nation.balance}")
    
    if nation.allies:
        allies_text = "\n".join([f"• {ally}" for ally in nation.allies])
        embed.add_field(name="Allies", value=allies_text or "No allies", inline=False)

    cursor = bot.db.conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM factions WHERE nation_id = ?', (nation.id,))
    faction_count = cursor.fetchone()[0]
    embed.add_field(name="Number of Factions", value=faction_count)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="form-alliance", description="Form an alliance with another nation")
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
async def grant_pass(interaction: discord.Interaction, user: discord.User, days: int = 30):
    granter = await bot.db.get_user(interaction.user.id)
    if not granter.nation_id:
        await interaction.response.send_message("Only nation leaders can grant passes!")
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
async def request_pass(interaction: discord.Interaction):
    user = await bot.db.get_user(interaction.user.id)
    
    if not user.faction_id and not user.nation_id:
        if user.balance < 5:
            await interaction.response.send_message("You need $5 to request a pass!")
            return
        await bot.db.modify_balance(user.id, -5)

    expiry_date = datetime.now() + timedelta(days=30)
    user_pass = await bot.db.create_user_pass(user.id, expiry_date)
    # ... similar to grant-pass command

@bot.tree.command(name="show-pass", description="Show your pass")
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
            check=lambda m: m.author == interaction.user and interaction.channel == m.channel and m.attachments
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
            check=lambda m: m.author == interaction.user and interaction.channel == m.channel and m.attachments
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
async def verify_pass(interaction: discord.Interaction, user: discord.User):
    verifier = await bot.db.get_user(interaction.user.id)
    target = await bot.db.get_user(user.id)
    
    # Check if verifier has permission (faction/nation leader or assigned role)
    if not (verifier.faction_id or verifier.nation_id):
        await interaction.response.send_message("You must be part of a faction or nation to verify passes!")
        return

    # For users not in any faction/nation, allow direct verification
    if not (target.faction_id or target.nation_id):
        user_pass = await bot.db.get_user_pass(user.id)
        if not user_pass:
            await interaction.response.send_message("User has no valid pass!")
            return
            
        await interaction.response.send_message(f"Requesting pass from {user.mention}. They should use /show-pass to display it.")
        return

    # For users in factions/nations, require pass display
    await interaction.response.send_message(
        f"Requesting pass from {user.mention}. They should use /show-pass to display it.\n"
        "Once they show their pass, use /check-pass to verify it."
    )

@bot.tree.command(name="check-pass", description="Check a displayed pass")
async def check_pass(interaction: discord.Interaction):
    if not interaction.message.attachments:
        await interaction.response.send_message("No pass image found in the message!")
        return

    # Download and verify the pass image
    attachment = interaction.message.attachments[0]
    if not attachment.filename.lower().endswith('.png'):
        await interaction.response.send_message("Invalid image format!")
        return

    # Save temporarily and verify
    temp_path = f"temp_verify_{interaction.id}.png"
    await attachment.save(temp_path)
    
    user_pass = await bot.db.get_user_pass(interaction.message.author.id)
    if not user_pass:
        await interaction.response.send_message("No pass data found for this user!")
        os.remove(temp_path)
        return

    is_valid, discrepancies, marked_image = pass_generator.verify_pass_image(temp_path, user_pass)
    os.remove(temp_path)

    if is_valid:
        await interaction.response.send_message("✅ Pass verification successful!")
    else:
        marked_path = f"marked_pass_{interaction.id}.png"
        marked_image.save(marked_path)
        await interaction.response.send_message(
            "❌ Pass verification failed!\nDiscrepancies found:\n" + "\n".join(f"- {d}" for d in discrepancies),
            file=discord.File(marked_path)
        )
        os.remove(marked_path)

bot.run('YOUR_BOT_TOKEN')
