import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
from discord import ButtonStyle, Interaction
from discord import PermissionOverwrite
from pymongo import MongoClient
import random
import string
import os
from datetime import datetime, timedelta, UTC
import asyncio

# MongoDB connection setup
client = MongoClient(os.getenv("MONGODB_URI"))
db = client["cashback_bot"]
users_collection = db["users"]
codes_collection = db["codes"]
transactions_collection = db["transactions"]
user_profiles_collection = db["user_profiles"]

# Rate limiting and cooldown settings
RATE_LIMIT = {
    "code_redeem": 5,  # Maximum attempts per minute
    "withdrawal": 3,   # Maximum attempts per hour
    "balance_check": 10  # Maximum attempts per minute
}

# Cooldown periods (in seconds)
COOLDOWN_PERIODS = {
    "code_redeem": 60,
    "withdrawal": 3600,
    "balance_check": 60
}

# Discord bot setup
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="$", intents=intents)

# Helper Functions
def generate_code(length=8):
    """Generate a random alphanumeric code."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def get_or_create_user(user_id):
    """Retrieve or create a user record with enhanced profile."""
    user = users_collection.find_one({"user_id": str(user_id)})
    if not user:
        user = {
            "user_id": str(user_id),
            "balance": 0.0,
            "total_earned": 0.0,
            "total_withdrawn": 0.0,
            "created_at": datetime.now(UTC),
            "last_transaction": None,
            "transaction_count": 0
        }
        users_collection.insert_one(user)
        
        # Create user profile
        profile = {
            "user_id": str(user_id),
            "level": 1,
            "xp": 0,
            "rank": "Bronze",
            "achievements": [],
            "last_activity": datetime.now(UTC),
            "transaction_count": 0
        }
        user_profiles_collection.insert_one(profile)
    return user

def create_transaction(user_id, amount, transaction_type, status="completed"):
    """Create a transaction record."""
    transaction = {
        "user_id": str(user_id),
        "amount": amount,
        "type": transaction_type,
        "status": status,
        "timestamp": datetime.now(UTC),
        "transaction_id": ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    }
    transactions_collection.insert_one(transaction)
    return transaction

def update_user_profile(user_id, amount, transaction_type):
    """Update user profile with new transaction."""
    profile = user_profiles_collection.find_one({"user_id": str(user_id)})
    if not profile:
        return
    
    # Update XP based on transaction amount (1 XP per dollar)
    xp_gained = int(amount)
    new_xp = profile.get("xp", 0) + xp_gained
    
    # Level up system (1000 XP per level)
    new_level = (new_xp // 1000) + 1
    
    # Rank system
    ranks = ["Bronze", "Silver", "Gold", "Platinum", "Diamond"]
    rank_index = min((new_level - 1) // 5, len(ranks) - 1)
    new_rank = ranks[rank_index]
    
    # Update profile
    user_profiles_collection.update_one(
        {"user_id": str(user_id)},
        {
            "$set": {
                "level": new_level,
                "xp": new_xp,
                "rank": new_rank,
                "last_activity": datetime.now(UTC)
            },
            "$inc": {"transaction_count": 1}
        }
    )

async def send_notification(user, message, interaction=None):
    """Send notification to user."""
    try:
        if interaction:
            await interaction.followup.send(message, ephemeral=True)
        else:
            user_obj = await bot.fetch_user(int(user["user_id"]))
            await user_obj.send(message)
    except Exception as e:
        print(f"Failed to send notification: {e}")

# Modal Classes
class RedeemCodeModal(Modal, title="Redeem Cashback Code"):
    code_input = TextInput(label="Enter your code:", placeholder="e.g., ABC123")

    async def on_submit(self, interaction: Interaction):
        # Rate limiting check
        user_id = str(interaction.user.id)
        recent_transactions = transactions_collection.count_documents({
            "user_id": user_id,
            "type": "code_redeem",
            "timestamp": {"$gte": datetime.now(UTC) - timedelta(minutes=1)}
        })
        
        if recent_transactions >= RATE_LIMIT["code_redeem"]:
            await interaction.response.send_message(
                "❌ You've reached the rate limit. Please wait before trying again.",
                ephemeral=True
            )
            return

        code = self.code_input.value.strip()
        code_data = codes_collection.find_one({"code": code, "redeemed": False})

        if not code_data:
            await interaction.response.send_message("❌ Invalid or already redeemed code.", ephemeral=True)
            return

        reward = code_data["amount"]
        user = get_or_create_user(interaction.user.id)
        
        # Update user balance and create transaction
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$inc": {
                    "balance": reward,
                    "total_earned": reward
                },
                "$set": {"last_transaction": datetime.now(UTC)}
            }
        )
        
        # Create transaction record
        transaction = create_transaction(user_id, reward, "code_redeem")
        
        # Update user profile
        update_user_profile(user_id, reward, "code_redeem")
        
        # Mark code as redeemed
        codes_collection.update_one({"code": code}, {"$set": {"redeemed": True}})

        # Create success embed
        embed = discord.Embed(
            title="🎉 Code Redeemed Successfully!",
            description=f"You've received **${reward:.2f}** cashback.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Transaction ID", value=transaction["transaction_id"], inline=False)
        embed.add_field(name="New Balance", value=f"**${user['balance'] + reward:.2f}**", inline=True)
        embed.set_footer(text="Cashback System")
        
        # Send notification
        notification = f"✅ Successfully redeemed code for **${reward:.2f}**! Your new balance is **${user['balance'] + reward:.2f}**"
        await send_notification(user, notification, interaction)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

class WithdrawModal(Modal, title="Withdraw Cashback"):
    amount_input = TextInput(label="Enter withdrawal amount:", placeholder="e.g., 10.00")

    def __init__(self, category_name: str, channel_name: str):
        super().__init__()
        self.category_name = category_name
        self.channel_name = channel_name

    async def on_submit(self, interaction: Interaction):
        # Rate limiting check
        user_id = str(interaction.user.id)
        recent_transactions = transactions_collection.count_documents({
            "user_id": user_id,
            "type": "withdrawal",
            "timestamp": {"$gte": datetime.now(UTC) - timedelta(hours=1)}
        })
        
        if recent_transactions >= RATE_LIMIT["withdrawal"]:
            await interaction.response.send_message(
                "❌ You've reached the withdrawal rate limit. Please wait before trying again.",
                ephemeral=True
            )
            return

        user = get_or_create_user(interaction.user.id)
        balance = user["balance"]

        try:
            amount = float(self.amount_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid amount entered. Please enter a valid number.", ephemeral=True)
            return

        if amount > balance:
            await interaction.response.send_message(
                f"❌ Insufficient balance. You only have **${balance:.2f}**.", ephemeral=True
            )
            return
        if amount < 1.0:
            await interaction.response.send_message(
                "❌ Minimum withdrawal amount is $1.00.", ephemeral=True
            )
            return

        # Create transaction record
        transaction = create_transaction(user_id, amount, "withdrawal", status="pending")
        
        # Update user balance
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$inc": {
                    "balance": -amount,
                    "total_withdrawn": amount
                },
                "$set": {"last_transaction": datetime.now(UTC)}
            }
        )

        guild = interaction.guild
        category = discord.utils.get(guild.categories, name=self.category_name)
        if not category:
            category = await guild.create_category(self.category_name)

        channel = discord.utils.get(category.channels, name=self.channel_name)
        if not channel:
            channel = await category.create_text_channel(self.channel_name)

        # Set permissions
        overwrite = PermissionOverwrite()
        overwrite.read_messages = True
        await channel.set_permissions(interaction.user, overwrite=overwrite)

        overwrite = PermissionOverwrite()
        overwrite.read_messages = False
        await channel.set_permissions(guild.default_role, overwrite=overwrite)

        embed = discord.Embed(
            title="💳 Withdrawal Request",
            description="A new withdrawal request has been submitted.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="User", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
        embed.add_field(name="Amount", value=f"**${amount:.2f}**", inline=True)
        embed.add_field(name="Transaction ID", value=transaction["transaction_id"], inline=True)
        embed.add_field(name="Remaining Balance", value=f"**${balance - amount:.2f}**", inline=True)
        embed.set_footer(text="Cashback System")

        server_owner = guild.owner
        await channel.send(
            content=f"{server_owner.mention}",
            embed=embed,
            view=StaffButtonsView(interaction.user.id, amount, balance - amount, channel, guild, transaction["transaction_id"])
        )

        # Send notification
        notification = f"✅ Withdrawal request for **${amount:.2f}** submitted. Your new balance is **${balance - amount:.2f}**"
        await send_notification(user, notification, interaction)
        
        await interaction.response.send_message(
            f"✅ Withdrawal request for **${amount:.2f}** submitted. The server owner has been notified.",
            ephemeral=True
        )


class StaffButtonsView(View):
    def __init__(self, user_id, amount, remaining_balance, channel, guild, transaction_id):
        super().__init__()
        self.user_id = user_id
        self.amount = amount
        self.remaining_balance = remaining_balance
        self.channel = channel
        self.guild = guild
        self.transaction_id = transaction_id
        self.staff_channel = discord.utils.get(guild.text_channels, name="staff-log-channel")

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ You don't have permission to approve withdrawals.", ephemeral=True)
            return

        # Update transaction status
        transactions_collection.update_one(
            {"transaction_id": self.transaction_id},
            {"$set": {"status": "completed"}}
        )

        # Get user for notification
        user = get_or_create_user(self.user_id)
        
        # Send approval notification
        notification = f"✅ Your withdrawal request for **${self.amount:.2f}** has been approved!"
        await send_notification(user, notification)

        # Update embed
        embed = discord.Embed(
            title="💳 Withdrawal Request",
            description="This withdrawal request has been approved.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="User", value=f"<@{self.user_id}> ({self.user_id})", inline=False)
        embed.add_field(name="Amount", value=f"**${self.amount:.2f}**", inline=True)
        embed.add_field(name="Transaction ID", value=self.transaction_id, inline=True)
        embed.add_field(name="Remaining Balance", value=f"**${self.remaining_balance:.2f}**", inline=True)
        embed.add_field(name="Approved By", value=interaction.user.mention, inline=True)
        embed.set_footer(text="Cashback System")

        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message("✅ Withdrawal request approved.", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ You don't have permission to reject withdrawals.", ephemeral=True)
            return

        # Update transaction status
        transactions_collection.update_one(
            {"transaction_id": self.transaction_id},
            {"$set": {"status": "rejected"}}
        )

        # Refund the user's balance
        users_collection.update_one(
            {"user_id": self.user_id},
            {"$inc": {"balance": self.amount}}
        )

        # Get user for notification
        user = get_or_create_user(self.user_id)
        
        # Send rejection notification
        notification = f"❌ Your withdrawal request for **${self.amount:.2f}** has been rejected. The amount has been refunded to your balance."
        await send_notification(user, notification)

        # Update embed
        embed = discord.Embed(
            title="💳 Withdrawal Request",
            description="This withdrawal request has been rejected.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="User", value=f"<@{self.user_id}> ({self.user_id})", inline=False)
        embed.add_field(name="Amount", value=f"**${self.amount:.2f}**", inline=True)
        embed.add_field(name="Transaction ID", value=self.transaction_id, inline=True)
        embed.add_field(name="Remaining Balance", value=f"**${self.remaining_balance + self.amount:.2f}**", inline=True)
        embed.add_field(name="Rejected By", value=interaction.user.mention, inline=True)
        embed.set_footer(text="Cashback System")

        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message("✅ Withdrawal request rejected.", ephemeral=True)

    @discord.ui.button(label="Transcript", style=discord.ButtonStyle.primary)
    async def transcript_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.user_id or interaction.user.guild_permissions.manage_messages:
            if not self.staff_channel:
                await interaction.response.send_message("❌ Staff log channel not found.", ephemeral=True)
                return

            transaction = transactions_collection.find_one({"transaction_id": self.transaction_id})
            if not transaction:
                await interaction.response.send_message("❌ Transaction not found.", ephemeral=True)
                return

            embed = discord.Embed(
                title="Withdrawal Request Transcript",
                description=f"Details of the withdrawal request by <@{self.user_id}>",
                color=discord.Color.blue(),
            )
            embed.add_field(name="User", value=f"<@{self.user_id}> ({self.user_id})", inline=False)
            embed.add_field(name="Amount Requested", value=f"${self.amount:.2f}", inline=True)
            embed.add_field(name="Transaction ID", value=self.transaction_id, inline=True)
            embed.add_field(name="Status", value=transaction["status"].title(), inline=True)
            embed.add_field(name="Date", value=transaction["timestamp"].strftime('%Y-%m-%d %H:%M:%S'), inline=True)
            await self.staff_channel.send(embed=embed)
            await interaction.response.send_message("✅ Transcript sent to the staff log channel.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ You do not have permission to view the transcript.", ephemeral=True)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.user_id or interaction.user.guild_permissions.manage_messages:
            # Lock the channel
            overwrite = PermissionOverwrite()
            overwrite.read_messages = False
            await self.channel.set_permissions(self.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message("✅ The withdrawal request has been closed and the channel is locked.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ You do not have permission to close the request.", ephemeral=True)

# Cashback Panel with Buttons
class CashbackPanel(View):
    @discord.ui.button(label="Redeem Code", style=ButtonStyle.primary, custom_id="redeem_code")
    async def redeem_code_button(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(RedeemCodeModal())

    @discord.ui.button(label="Check Balance", style=ButtonStyle.secondary, custom_id="check_balance")
    async def check_balance_button(self, interaction: Interaction, button: Button):
        user = get_or_create_user(interaction.user.id)
        balance = user["balance"]
        embed = discord.Embed(
            title="💰 Your Balance",
            description=f"You currently have **${balance:.2f}** cashback.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Cashback System")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Withdraw", style=ButtonStyle.success, custom_id="withdraw")
    async def withdraw_button(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(
            WithdrawModal(category_name="Withdrawals", channel_name="withdrawal-requests")
        )
# Panel Command
@bot.command(name="panel")
@commands.has_role("Staff")  # Check if the user has the "Staff" role
async def panel(ctx):
    """Displays the cashback panel with buttons."""
    embed = discord.Embed(
        title="💸 Cashback Panel",
        description="Use the buttons below to manage your cashback.",
        color=discord.Color.purple(),
    )
    embed.set_image(url="https://media.discordapp.net/attachments/1317341355625939005/1326194161338159145/lines.gif?ex=6780844f&is=677f32cf&hm=91226d14e879196ed82dadf934312daf203da91d59bad7b3cb2b58cab10ddc46&=&width=642&height=9")  # Replace with your image URL
    embed.add_field(name="Redeem Code", value="Redeem a cashback code.", inline=False)
    embed.add_field(name="Check Balance", value="View your current cashback balance.", inline=False)
    embed.add_field(name="Withdraw", value="Submit a withdrawal request.", inline=False)
    embed.set_footer(text="Cashback System")
    
    try:
        await ctx.send(embed=embed, view=CashbackPanel())
    except discord.Forbidden:
        await ctx.send(f"❌ Couldn't send panel to {ctx.author.mention}. Ensure your DMs are open.")

@bot.command(name="transactions")
async def view_transactions(ctx, page: int = 1):
    """View your transaction history."""
    # Rate limiting check
    user_id = str(ctx.author.id)
    recent_checks = transactions_collection.count_documents({
        "user_id": user_id,
        "type": "balance_check",
        "timestamp": {"$gte": datetime.now(UTC) - timedelta(minutes=1)}
    })
    
    if recent_checks >= RATE_LIMIT["balance_check"]:
        await ctx.send("❌ You've reached the rate limit. Please wait before checking again.", ephemeral=True)
        return

    # Get transactions with pagination
    per_page = 5
    skip = (page - 1) * per_page
    transactions = list(transactions_collection.find(
        {"user_id": user_id}
    ).sort("timestamp", -1).skip(skip).limit(per_page))

    if not transactions:
        await ctx.send("No transactions found.", ephemeral=True)
        return

    # Create transaction history embed
    embed = discord.Embed(
        title="📜 Transaction History",
        description=f"Showing transactions for {ctx.author.mention}",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow(),
    )

    for transaction in transactions:
        status_emoji = "✅" if transaction["status"] == "completed" else "⏳" if transaction["status"] == "pending" else "❌"
        amount_prefix = "+" if transaction["type"] == "code_redeem" else "-"
        embed.add_field(
            name=f"{status_emoji} {transaction['type'].title()}",
            value=f"Amount: {amount_prefix}${transaction['amount']:.2f}\nID: {transaction['transaction_id']}\nDate: {transaction['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}",
            inline=False
        )

    # Add pagination info
    total_transactions = transactions_collection.count_documents({"user_id": user_id})
    total_pages = (total_transactions + per_page - 1) // per_page
    embed.set_footer(text=f"Page {page}/{total_pages} • Cashback System")

    await ctx.send(embed=embed, ephemeral=True)

@bot.command(name="profile")
async def view_profile(ctx, member: discord.Member = None):
    """View your or another user's profile."""
    if member is None:
        member = ctx.author

    # Rate limiting check
    user_id = str(ctx.author.id)
    recent_checks = transactions_collection.count_documents({
        "user_id": user_id,
        "type": "profile_check",
        "timestamp": {"$gte": datetime.now(UTC) - timedelta(minutes=1)}
    })
    
    if recent_checks >= RATE_LIMIT["balance_check"]:
        await ctx.send("❌ You've reached the rate limit. Please wait before checking again.", ephemeral=True)
        return

    user = get_or_create_user(member.id)
    profile = user_profiles_collection.find_one({"user_id": str(member.id)})

    if not profile:
        await ctx.send("Profile not found.", ephemeral=True)
        return

    # Create profile embed
    embed = discord.Embed(
        title=f"👤 {member.name}'s Profile",
        description=f"Rank: {profile['rank']} • Level {profile['level']}",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow(),
    )

    # Add profile information
    embed.add_field(name="Balance", value=f"**${user['balance']:.2f}**", inline=True)
    embed.add_field(name="Total Earned", value=f"**${user['total_earned']:.2f}**", inline=True)
    embed.add_field(name="Total Withdrawn", value=f"**${user['total_withdrawn']:.2f}**", inline=True)
    embed.add_field(name="XP", value=f"**{profile['xp']}** / {profile['level'] * 1000}", inline=True)
    embed.add_field(name="Transactions", value=f"**{profile['transaction_count']}**", inline=True)
    embed.add_field(name="Member Since", value=user['created_at'].strftime('%Y-%m-%d'), inline=True)

    # Add achievements if any
    if profile['achievements']:
        achievements_text = "\n".join([f"🏆 {achievement}" for achievement in profile['achievements']])
        embed.add_field(name="Achievements", value=achievements_text, inline=False)

    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    embed.set_footer(text="Cashback System")

    await ctx.send(embed=embed, ephemeral=True)

@bot.command(name="generate_code")
@commands.has_role("Staff")
async def generate_code(ctx, amount: float):
    """Generate a new cashback code."""
    if amount <= 0:
        await ctx.send("❌ Amount must be greater than 0.", ephemeral=True)
        return

    code = generate_code()
    code_data = {
        "code": code,
        "amount": amount,
        "redeemed": False,
        "created_at": datetime.now(UTC),
        "created_by": str(ctx.author.id)
    }
    codes_collection.insert_one(code_data)

    embed = discord.Embed(
        title="🎫 New Cashback Code Generated",
        description=f"Amount: **${amount:.2f}**",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Code", value=f"`{code}`", inline=False)
    embed.add_field(name="Generated By", value=ctx.author.mention, inline=True)
    embed.set_footer(text="Cashback System")

    await ctx.send(embed=embed, ephemeral=True)

@bot.command(name="view_codes")
@commands.has_role("Staff")
async def view_codes(ctx, status: str = "all"):
    """View all cashback codes with optional status filter."""
    query = {}
    if status.lower() == "active":
        query["redeemed"] = False
    elif status.lower() == "redeemed":
        query["redeemed"] = True

    codes = list(codes_collection.find(query).sort("created_at", -1))

    if not codes:
        await ctx.send("No codes found.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🎫 Cashback Codes",
        description=f"Showing {status.title()} Codes",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow(),
    )

    for code in codes:
        status_emoji = "✅" if code["redeemed"] else "🆕"
        status_text = "Redeemed" if code["redeemed"] else "Active"
        value = f"Amount: **${code['amount']:.2f}**\n"
        value += f"Created: {code['created_at'].strftime('%Y-%m-%d %H:%M:%S')}\n"
        if code["redeemed"]:
            value += f"Redeemed By: <@{code.get('redeemed_by', 'Unknown')}>\n"
            value += f"Redeemed At: {code.get('redeemed_at', 'Unknown')}"
        
        embed.add_field(
            name=f"{status_emoji} {code['code']} ({status_text})",
            value=value,
            inline=False
        )

    embed.set_footer(text="Cashback System")
    await ctx.send(embed=embed, ephemeral=True)

@bot.command(name="view_withdrawals")
@commands.has_role("Staff")
async def view_withdrawals(ctx, status: str = "pending"):
    """View all withdrawal requests with optional status filter."""
    query = {"type": "withdrawal"}
    if status.lower() == "pending":
        query["status"] = "pending"
    elif status.lower() == "completed":
        query["status"] = "completed"
    elif status.lower() == "rejected":
        query["status"] = "rejected"

    withdrawals = list(transactions_collection.find(query).sort("timestamp", -1))

    if not withdrawals:
        await ctx.send("No withdrawal requests found.", ephemeral=True)
        return

    embed = discord.Embed(
        title="💳 Withdrawal Requests",
        description=f"Showing {status.title()} Withdrawals",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow(),
    )

    for withdrawal in withdrawals:
        status_emoji = "✅" if withdrawal["status"] == "completed" else "⏳" if withdrawal["status"] == "pending" else "❌"
        value = f"Amount: **${withdrawal['amount']:.2f}**\n"
        value += f"User: <@{withdrawal['user_id']}>\n"
        value += f"Date: {withdrawal['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}\n"
        value += f"ID: {withdrawal['transaction_id']}"
        
        embed.add_field(
            name=f"{status_emoji} Withdrawal Request",
            value=value,
            inline=False
        )

    embed.set_footer(text="Cashback System")
    await ctx.send(embed=embed, ephemeral=True)

@bot.command(name="stats")
@commands.has_role("Staff")
async def view_stats(ctx):
    """View system statistics."""
    total_users = users_collection.count_documents({})
    total_transactions = transactions_collection.count_documents({})
    total_codes = codes_collection.count_documents({})
    active_codes = codes_collection.count_documents({"redeemed": False})
    pending_withdrawals = transactions_collection.count_documents({"type": "withdrawal", "status": "pending"})
    
    # Calculate total amounts
    pipeline = [
        {"$group": {
            "_id": None,
            "total_earned": {"$sum": "$total_earned"},
            "total_withdrawn": {"$sum": "$total_withdrawn"},
            "current_balance": {"$sum": "$balance"}
        }}
    ]
    totals = list(users_collection.aggregate(pipeline))[0]

    embed = discord.Embed(
        title="📊 System Statistics",
        description="Current system status and metrics",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow(),
    )

    embed.add_field(name="Total Users", value=f"**{total_users}**", inline=True)
    embed.add_field(name="Total Transactions", value=f"**{total_transactions}**", inline=True)
    embed.add_field(name="Active Codes", value=f"**{active_codes}/{total_codes}**", inline=True)
    embed.add_field(name="Pending Withdrawals", value=f"**{pending_withdrawals}**", inline=True)
    embed.add_field(name="Total Earned", value=f"**${totals['total_earned']:.2f}**", inline=True)
    embed.add_field(name="Total Withdrawn", value=f"**${totals['total_withdrawn']:.2f}**", inline=True)
    embed.add_field(name="Current Balance", value=f"**${totals['current_balance']:.2f}**", inline=True)

    embed.set_footer(text="Cashback System")
    await ctx.send(embed=embed, ephemeral=True)

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors."""
    if isinstance(error, commands.MissingRole):
        await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: {error.param.name}", ephemeral=True)
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Invalid argument provided.", ephemeral=True)
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Command not found.", ephemeral=True)
    else:
        print(f"Error: {error}")
        await ctx.send("❌ An error occurred while processing your command.", ephemeral=True)

@bot.event
async def on_ready():
    """Handle bot ready event."""
    print(f"Bot is ready! Logged in as {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# Run the bot
bot.run("Your Discord Token") 
