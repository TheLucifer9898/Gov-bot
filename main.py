import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import random
import time
import asyncio
import os
TOKEN = os.getenv("TOKEN")
GUILD_ID = 1486940108862001276

# ---------------- BOT SETUP ----------------
intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- DATABASE ----------------
conn = sqlite3.connect("govsim.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS global_taxes (
    tax_type TEXT PRIMARY KEY,
    rate REAL DEFAULT 0.1
)
""")

# default values
cursor.execute("""
INSERT OR IGNORE INTO global_taxes VALUES ('industry', 0.10)
""")

cursor.execute("""
INSERT OR IGNORE INTO global_taxes VALUES ('service', 0.08)
""")

conn.commit()

# ---------------- TABLES ----------------
cursor.execute("""
CREATE TABLE IF NOT EXISTS citizens (
    user_id INTEGER PRIMARY KEY,
    cid INTEGER,
    holder_name TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS accounts (
    account_name TEXT PRIMARY KEY,
    owner_id INTEGER,
    role_id INTEGER,
    holder_name TEXT,
    account_type TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS balances (
    account_name TEXT,
    resource TEXT,
    amount INTEGER DEFAULT 0,
    PRIMARY KEY (account_name, resource)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS resources (
    name TEXT PRIMARY KEY
)
""")

conn.commit()
cursor.execute("""
CREATE TABLE IF NOT EXISTS market (
    resource TEXT PRIMARY KEY,
    buy_price INTEGER,
    sell_price INTEGER,
    govt_stock INTEGER DEFAULT 0
)
""")

conn.commit()
cursor.execute("""
CREATE TABLE IF NOT EXISTS industries (
    company_name TEXT PRIMARY KEY,
    owner_id INTEGER,
    produced_resource TEXT,
    inputs TEXT,
    level INTEGER,
    employees INTEGER,
    last_tick INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS employees (
    company_name TEXT,
    user_id INTEGER,
    salary INTEGER DEFAULT 0,
    role TEXT,
    PRIMARY KEY (company_name, user_id)
)
""")

conn.commit()
cursor.execute("""
CREATE TABLE IF NOT EXISTS service_companies (
    company_name TEXT PRIMARY KEY,
    owner_id INTEGER,
    level INTEGER,
    created_at INTEGER
)
""")

conn.commit()

SECONDS_IN_DAY = 86400




# ---------------- HELPERS ----------------
def get_next_cid():
    cursor.execute("SELECT MAX(cid) FROM citizens")
    last = cursor.fetchone()[0]
    return 1 if last is None else last + 1


def ensure_balance(account, resource):
    cursor.execute(
        "INSERT OR IGNORE INTO balances VALUES (?, ?, 0)",
        (account, resource)
    )
def has_access(interaction, account_name):
    cursor.execute("""
        SELECT owner_id FROM accounts WHERE account_name=?
    """, (account_name,))

    row = cursor.fetchone()

    if not row:
        return False

    owner_id = row[0]

    return interaction.user.id == owner_id or interaction.user.guild_permissions.administrator
def ensure_account_balance(account_name, resource):
    cursor.execute("""
        INSERT OR IGNORE INTO balances VALUES (?, ?, 0)
    """, (account_name, resource))
GOV_ACCOUNT = "Ministry of Finance"
cursor.execute("""
INSERT OR IGNORE INTO balances VALUES (?, 'Cash', 0)
""", (GOV_ACCOUNT,))

conn.commit()
def get_tax_rate(tax_type: str):
    cursor.execute("""
        SELECT rate FROM global_taxes WHERE tax_type=?
    """, (tax_type,))
    
    row = cursor.fetchone()
    return row[0] if row else 0.0

# ---------------- READY ----------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    if not hasattr(bot, "production_started"):
        bot.loop.create_task(production_tick())
        bot.production_started = True
        print("🏭 Economy production system started")

    guild = discord.Object(id=GUILD_ID)
    synced = await bot.tree.sync(guild=guild)

    print(f"✅ Synced {len(synced)} commands")

    # start economy production loop (only once)
    bot.loop.create_task(production_tick())
    print("🏭 Economy production system started")

# =========================================================
# REGISTER CITIZEN (NO ACCOUNT CREATED HERE)
# =========================================================
@bot.tree.command(name="register_citizen")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def register_citizen(interaction: discord.Interaction, member: discord.Member):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only", ephemeral=True)

    cursor.execute("SELECT cid FROM citizens WHERE user_id=?", (member.id,))
    if cursor.fetchone():
        return await interaction.response.send_message("⚠️ Already registered", ephemeral=True)

    cid = get_next_cid()
    holder_name = member.display_name

    cursor.execute(
        "INSERT INTO citizens VALUES (?, ?, ?)",
        (member.id, cid, holder_name)
    )

    conn.commit()

    await interaction.response.send_message(
        f"✅ Citizen Registered\n"
        f"👤 {member.mention}\n"
        f"🆔 CID: {cid}\n"
        f"ℹ️ Use /create_account to create accounts"
    )


# =========================================================
# CREATE ACCOUNT (ADMIN CONTROLLED)
# =========================================================
@bot.tree.command(name="create_account")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.choices(category=[
    app_commands.Choice(name="Personal", value="personal"),
    app_commands.Choice(name="Business", value="business"),
    app_commands.Choice(name="Government", value="government"),
])
async def create_account(
    interaction: discord.Interaction,
    member: discord.Member,
    account_name: str,
    category: app_commands.Choice[str],
    role: discord.Role = None
):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only", ephemeral=True)

    cursor.execute("SELECT account_name FROM accounts WHERE account_name=?", (account_name,))
    if cursor.fetchone():
        return await interaction.response.send_message("❌ Account exists", ephemeral=True)

    role_id = role.id if role else None

    cursor.execute("""
        INSERT INTO accounts VALUES (?, ?, ?, ?, ?)
    """, (account_name, member.id, role_id, member.display_name, category.value))

    conn.commit()

    await interaction.response.send_message(
        f"✅ Account Created\n"
        f"🏦 {account_name}\n"
        f"👤 Owner: {member.mention}\n"
        f"📂 Type: {category.value}\n"
        f"🎭 Role Access: {role.mention if role else 'None'}"
    )

# =========================================================
# ADD RESOURCE
# =========================================================
@bot.tree.command(name="add_resource")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def add_resource(interaction: discord.Interaction, resource: str):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only", ephemeral=True)

    cursor.execute("INSERT OR IGNORE INTO resources VALUES (?)", (resource,))
    conn.commit()

    await interaction.response.send_message(f"✅ Resource {resource} added")


# =========================================================
# REMOVE RESOURCE
# =========================================================
@bot.tree.command(name="remove_resource")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def remove_resource(interaction: discord.Interaction, resource: str):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only", ephemeral=True)

    cursor.execute("DELETE FROM resources WHERE name=?", (resource,))
    cursor.execute("DELETE FROM balances WHERE resource=?", (resource,))
    conn.commit()

    await interaction.response.send_message(f"🗑️ Resource {resource} removed")


# =========================================================
# VIEW BALANCE (MULTI ACCOUNT)
# =========================================================
@bot.tree.command(name="balance")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def balance(interaction: discord.Interaction, account_name: str):

    cursor.execute("""
        SELECT owner_id, holder_name, account_type
        FROM accounts
        WHERE account_name=?
    """, (account_name,))

    acc = cursor.fetchone()
    if not acc:
        return await interaction.response.send_message("❌ Account not found", ephemeral=True)

    owner_id, holder_name, account_type = acc

    cursor.execute("""
        SELECT resource, amount
        FROM balances
        WHERE account_name=?
    """, (account_name,))

    data = cursor.fetchall()

    text = "\n".join([f"{r}: {a}" for r, a in data]) or "No resources"

    await interaction.response.send_message(
        f"🏦 Account: {account_name}\n"
        f"👤 Holder: {holder_name}\n"
        f"📂 Type: {account_type}\n\n"
        f"{text}",
        ephemeral=True
    )


# =========================================================
# ADD BALANCE
# =========================================================
@bot.tree.command(name="add_balance")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def add_balance(interaction: discord.Interaction, account_name: str, resource: str, amount: int):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only", ephemeral=True)

    ensure_balance(account_name, resource)

    cursor.execute("""
        INSERT INTO balances VALUES (?, ?, ?)
        ON CONFLICT(account_name, resource)
        DO UPDATE SET amount = amount + ?
    """, (account_name, resource, amount, amount))

    conn.commit()

    await interaction.response.send_message("✅ Balance added")


# =========================================================
# REMOVE BALANCE
# =========================================================
@bot.tree.command(name="remove_balance")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def remove_balance(interaction: discord.Interaction, account_name: str, resource: str, amount: int):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only", ephemeral=True)

    cursor.execute("""
        SELECT amount FROM balances
        WHERE account_name=? AND resource=?
    """, (account_name, resource))

    row = cursor.fetchone()

    if not row or row[0] < amount:
        return await interaction.response.send_message("❌ Not enough balance", ephemeral=True)

    cursor.execute("""
        UPDATE balances
        SET amount = amount - ?
        WHERE account_name=? AND resource=?
    """, (amount, account_name, resource))

    conn.commit()

    await interaction.response.send_message("✅ Balance removed")


## =========================================================
# TRANSFER SYSTEM (FIXED)
# =========================================================
@bot.tree.command(name="transfer")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def transfer(
    interaction: discord.Interaction,
    from_account: str,
    to_account: str,
    resource: str,
    amount: int
):

    # ---------------- ADMIN OR OWNER CHECK ----------------
    cursor.execute(
        "SELECT owner_id FROM accounts WHERE account_name=?",
        (from_account,)
    )
    row = cursor.fetchone()

    if not row:
        return await interaction.response.send_message(
            "❌ Source account not found",
            ephemeral=True
        )

    owner_id = row[0]

    if interaction.user.id != owner_id and not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ Not allowed to use this account",
            ephemeral=True
        )

    # ---------------- ENSURE ACCOUNTS EXIST ----------------
    cursor.execute(
        "SELECT account_name FROM accounts WHERE account_name=?",
        (to_account,)
    )
    if not cursor.fetchone():
        return await interaction.response.send_message(
            "❌ Destination account not found",
            ephemeral=True
        )

    ensure_balance(from_account, resource)
    ensure_balance(to_account, resource)

    # ---------------- CHECK BALANCE ----------------
    cursor.execute(
        "SELECT amount FROM balances WHERE account_name=? AND resource=?",
        (from_account, resource)
    )
    row = cursor.fetchone()

    if not row or row[0] < amount:
        return await interaction.response.send_message(
            "❌ Insufficient balance",
            ephemeral=True
        )

    # ---------------- TRANSFER ----------------
    cursor.execute(
        "UPDATE balances SET amount = amount - ? WHERE account_name=? AND resource=?",
        (amount, from_account, resource)
    )

    cursor.execute("""
    INSERT INTO balances VALUES (?, ?, ?)
    ON CONFLICT(account_name, resource)
    DO UPDATE SET amount = amount + ?
""", (to_account, resource, amount, amount))

    conn.commit()

    await interaction.response.send_message("✅ Transfer complete")
@bot.tree.command(name="accounts")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def accounts(interaction: discord.Interaction, member: discord.Member):

    cursor.execute("""
        SELECT account_name, account_type
        FROM accounts
        WHERE owner_id=?
    """, (member.id,))

    data = cursor.fetchall()

    if not data:
        return await interaction.response.send_message("❌ No accounts", ephemeral=True)

    text = "\n".join([f"{a} ({t})" for a, t in data])

    await interaction.response.send_message(
        f"👤 {member.mention} Accounts:\n\n{text}",
        ephemeral=True
    )
@bot.tree.command(name="ledger")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def ledger(interaction: discord.Interaction, account_name: str):

    cursor.execute("""
        SELECT holder_name, account_type
        FROM accounts
        WHERE account_name=?
    """, (account_name,))

    acc = cursor.fetchone()
    if not acc:
        return await interaction.response.send_message("❌ Account not found", ephemeral=True)

    holder, acc_type = acc

    cursor.execute("""
        SELECT resource, amount
        FROM balances
        WHERE account_name=?
        ORDER BY resource
    """, (account_name,))

    data = cursor.fetchall()

    total = sum([a for _, a in data])

    text = "\n".join([f"{r}: {a}" for r, a in data]) or "No resources"

    await interaction.response.send_message(
        f"🏦 {account_name}\n"
        f"👤 Holder: {holder}\n"
        f"📂 Type: {acc_type}\n"
        f"💰 Total Units: {total}\n\n{text}",
        ephemeral=True
    )
@bot.tree.command(name="top_accounts")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def top_accounts(interaction: discord.Interaction):

    cursor.execute("""
        SELECT account_name, SUM(amount) as total
        FROM balances
        GROUP BY account_name
        ORDER BY total DESC
        LIMIT 10
    """)

    data = cursor.fetchall()

    if not data:
        return await interaction.response.send_message("No data")

    text = "\n".join([f"{i+1}. {name} → {total}" for i, (name, total) in enumerate(data)])

    await interaction.response.send_message(
        f"🏆 Top Accounts:\n\n{text}"
    )
@bot.tree.command(name="resource_stats")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def resource_stats(interaction: discord.Interaction, resource: str):

    cursor.execute("""
        SELECT SUM(amount)
        FROM balances
        WHERE resource=?
    """, (resource,))

    total = cursor.fetchone()[0] or 0

    await interaction.response.send_message(
        f"📦 Total {resource} in economy: {total}"
    )
@bot.tree.command(name="economy_overview")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def economy_overview(interaction: discord.Interaction):

    # total accounts
    cursor.execute("SELECT COUNT(*) FROM accounts")
    accounts = cursor.fetchone()[0]

    # total citizens
    cursor.execute("SELECT COUNT(*) FROM citizens")
    citizens = cursor.fetchone()[0]

    # total resources
    cursor.execute("SELECT COUNT(DISTINCT resource) FROM balances")
    resources = cursor.fetchone()[0]

    await interaction.response.send_message(
        f"🌍 Economy Overview\n\n"
        f"👥 Citizens: {citizens}\n"
        f"🏦 Accounts: {accounts}\n"
        f"📦 Resource Types: {resources}"
    )
@bot.tree.command(name="accounts_by_type")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.choices(category=[
    app_commands.Choice(name="Personal", value="personal"),
    app_commands.Choice(name="Business", value="business"),
    app_commands.Choice(name="Government", value="government"),
])
async def accounts_by_type(interaction: discord.Interaction, category: app_commands.Choice[str]):

    cursor.execute("""
        SELECT account_name, holder_name
        FROM accounts
        WHERE account_type=?
    """, (category.value,))

    data = cursor.fetchall()

    if not data:
        return await interaction.response.send_message("No accounts")

    text = "\n".join([f"{a} → {h}" for a, h in data])

    await interaction.response.send_message(
        f"📂 {category.value} Accounts:\n\n{text}"
    )
@bot.tree.command(name="set_market")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def set_market(interaction: discord.Interaction, resource: str, buy_price: int, sell_price: int, stock: int):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only", ephemeral=True)

    cursor.execute("""
        INSERT OR REPLACE INTO market VALUES (?, ?, ?, ?)
    """, (resource, buy_price, sell_price, stock))

    conn.commit()

    await interaction.response.send_message(
        f"📊 Market Set\n"
        f"📦 {resource}\n"
        f"💰 Buy: {buy_price}\n"
        f"💸 Sell: {sell_price}\n"
        f"🏛 Govt Stock: {stock}"
    )
@bot.tree.command(name="sell")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def sell(interaction: discord.Interaction, account_name: str, resource: str, amount: int):

    cursor.execute("SELECT buy_price FROM market WHERE resource=?", (resource,))
    m = cursor.fetchone()

    if not m:
        return await interaction.response.send_message("❌ Not in market", ephemeral=True)

    price = m[0]
    total_value = price * amount

    # check player stock
    cursor.execute("""
        SELECT amount FROM balances
        WHERE account_name=? AND resource=?
    """, (account_name, resource))

    row = cursor.fetchone()
    if not row or row[0] < amount:
        return await interaction.response.send_message("❌ Not enough resources", ephemeral=True)

    # deduct from player
    cursor.execute("""
        UPDATE balances SET amount = amount - ?
        WHERE account_name=? AND resource=?
    """, (amount, account_name, resource))

    # give cash from govt
    ensure_balance(GOV_ACCOUNT, "Cash")

    cursor.execute("""
        INSERT INTO balances VALUES (?, ?, ?)
        ON CONFLICT(account_name, resource)
        DO UPDATE SET amount = amount + ?
    """, (account_name, "Cash", total_value, total_value))

    # deduct govt cash
    cursor.execute("""
        UPDATE balances SET amount = amount - ?
        WHERE account_name=? AND resource='Cash'
    """, (total_value, GOV_ACCOUNT))

    conn.commit()

    await interaction.response.send_message("💰 Sold successfully")
@bot.tree.command(name="market")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def market(interaction: discord.Interaction):

    cursor.execute("""
        SELECT resource, buy_price, sell_price, govt_stock
        FROM market
    """)

    data = cursor.fetchall()

    if len(data) == 0:
        return await interaction.response.send_message(
            "❌ No market data available right now.",
            ephemeral=True
        )

    embed = discord.Embed(
        title="🏛️ Government Market Board",
        description="Official prices controlled by Ministry of Finance",
        color=discord.Color.gold()
    )

    for resource, buy_price, sell_price, stock in data:
        embed.add_field(
            name=f"📦 {resource}",
            value=(
                f"💰 Buy Price: {buy_price}\n"
                f"🛒 Sell Price: {sell_price}\n"
                f"📊 Govt Stock: {stock}"
            ),
            inline=False
        )

    await interaction.response.send_message(embed=embed)

# =====================================================
# CREATE INDUSTRY
# =====================================================
@bot.tree.command(name="create_industry")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def create_industry(
    interaction: discord.Interaction,
    company_name: str,
    produced: str,
    inputs: str,
    level: int
):

    cursor.execute("SELECT company_name FROM industries WHERE company_name=?", (company_name,))
    if cursor.fetchone():
        return await interaction.response.send_message("❌ Company already exists", ephemeral=True)

    cursor.execute("""
        INSERT INTO industries VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        company_name,
        interaction.user.id,
        produced,
        inputs,
        level,
        0,
        int(time.time())
    ))

    conn.commit()

    await interaction.response.send_message(
        f"🏭 **{company_name} Created**\n"
        f"📦 Output: {produced}\n"
        f"📥 Inputs: {inputs}\n"
        f"📈 Level: {level}"
    )


# =====================================================
# HIRE
# =====================================================
@bot.tree.command(name="hire")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def hire(interaction: discord.Interaction, company_name: str, user: discord.Member, salary: int, role: str):

    # ✅ unified ownership check
    if not is_company_owner(company_name, interaction.user.id):
        return await interaction.response.send_message(
            "❌ Only owner can hire",
            ephemeral=True
        )

    # (optional safety check: ensure company exists)
    cursor.execute("""
        SELECT company_name FROM industries WHERE company_name=?
        UNION
        SELECT company_name FROM service_companies WHERE company_name=?
    """, (company_name, company_name))

    if not cursor.fetchone():
        return await interaction.response.send_message(
            "❌ Company not found",
            ephemeral=True
        )

    cursor.execute("""
        INSERT OR REPLACE INTO employees VALUES (?, ?, ?, ?)
    """, (company_name, user.id, salary, role))

    conn.commit()

    await interaction.response.send_message(
        f"👷 {user.mention} hired in {company_name}"
    )

# =====================================================
# FIRE
# =====================================================
@bot.tree.command(name="fire")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def fire(interaction: discord.Interaction, company_name: str, user: discord.Member):

    # ✅ unified ownership check
    if not is_company_owner(company_name, interaction.user.id):
        return await interaction.response.send_message(
            "❌ Only owner can fire",
            ephemeral=True
        )

    cursor.execute("""
        DELETE FROM employees 
        WHERE company_name=? AND user_id=?
    """, (company_name, user.id))

    conn.commit()

    await interaction.response.send_message(
        f"🔥 {user.mention} fired from {company_name}"
    )

# =====================================================
# EMPLOYEES
# =====================================================
@bot.tree.command(name="employees")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def employees(interaction: discord.Interaction, company_name: str):

    cursor.execute("""
        SELECT user_id, role, salary FROM employees WHERE company_name=?
    """, (company_name,))

    data = cursor.fetchall()

    if not data:
        return await interaction.response.send_message("❌ No employees", ephemeral=True)

    text = ""

    for uid, role, salary in data:
        user = await bot.fetch_user(uid)
        text += f"👤 {user.name} | {role} | 💰 {salary}\n"

    await interaction.response.send_message(text)


# =====================================================
# COMPANY INFO
# =====================================================
@bot.tree.command(name="company_info")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def company_info(interaction: discord.Interaction, company_name: str):

    cursor.execute("""
        SELECT owner_id, produced_resource, inputs, level
        FROM industries WHERE company_name=?
    """, (company_name,))

    row = cursor.fetchone()

    if not row:
        return await interaction.response.send_message("❌ Company not found", ephemeral=True)

    owner_id, resource, inputs, level = row
    owner = await bot.fetch_user(owner_id)

    cursor.execute("SELECT COUNT(*) FROM employees WHERE company_name=?", (company_name,))
    emp_count = cursor.fetchone()[0]

    production = emp_count * level * 5

    await interaction.response.send_message(
        f"🏢 **{company_name}**\n"
        f"👑 Owner: {owner.name}\n"
        f"📦 Produces: {resource}\n"
        f"📥 Inputs: {inputs}\n"
        f"📈 Level: {level}\n"
        f"👷 Employees: {emp_count}\n"
        f"⚙ Production/day: {production}"
    )
@bot.tree.command(name="service_company_info")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def service_company_info(interaction: discord.Interaction, company_name: str):

    cursor.execute("""
        SELECT owner_id, level, created_at
        FROM service_companies
        WHERE company_name=?
    """, (company_name,))

    row = cursor.fetchone()

    if not row:
        return await interaction.response.send_message(
            "❌ Service company not found",
            ephemeral=True
        )

    owner_id, level, created_at = row
    owner = await bot.fetch_user(owner_id)

    cursor.execute("""
        SELECT COUNT(*) FROM employees WHERE company_name=?
    """, (company_name,))

    emp_count = cursor.fetchone()[0]

    await interaction.response.send_message(
        f"⚖️ Service Company: {company_name}\n"
        f"👤 Owner: {owner.name}\n"
        f"📈 Level: {level}\n"
        f"👷 Employees: {emp_count}\n"
        f"🧾 Type: Service (no production)\n"
)
# =====================================================
# PRODUCTION SYSTEM (REAL ECONOMY)
# =====================================================
async def production_tick():
    await bot.wait_until_ready()

    while not bot.is_closed():
        now = int(time.time())

        cursor.execute("""
            SELECT company_name, produced_resource, inputs, level, last_tick
            FROM industries
        """)

        companies = cursor.fetchall()

        for company, output, inputs, level, last_tick in companies:

            if now - last_tick < SECONDS_IN_DAY:
                continue
            cursor.execute("SELECT COUNT(*) FROM employees WHERE company_name=?", (company,))
            employees = cursor.fetchone()[0]

            production_amount = employees * level * 5

            # ---------------- CONSUME INPUTS ----------------
            if inputs:
                for item in inputs.split(","):
                    res, qty = item.split(":")
                    qty = int(qty) * production_amount

                    cursor.execute("""
                        SELECT amount FROM balances
                        WHERE account_name=? AND resource=?
                    """, (company, res))

                    row = cursor.fetchone()

                    if not row or row[0] < qty:
                        break  # skip production if not enough
                else:
                    # deduct inputs
                    for item in inputs.split(","):
                        res, qty = item.split(":")
                        qty = int(qty) * production_amount

                        cursor.execute("""
                            UPDATE balances
                            SET amount = amount - ?
                            WHERE account_name=? AND resource=?
                        """, (qty, company, res))

                    # add output
                    cursor.execute("""
                        INSERT INTO balances VALUES (?, ?, ?)
                        ON CONFLICT(account_name, resource)
                        DO UPDATE SET amount = amount + ?
                    """, (company, output, production_amount, production_amount))

            else:
                cursor.execute("""
                    INSERT INTO balances VALUES (?, ?, ?)
                    ON CONFLICT(account_name, resource)
                    DO UPDATE SET amount = amount + ?
                """, (company, output, production_amount, production_amount))

            cursor.execute("""
                UPDATE industries SET last_tick=? WHERE company_name=?
            """, (now, company))

        conn.commit()
        await asyncio.sleep(600)
@bot.tree.command(name="create_service_company")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def create_service_company(
    interaction: discord.Interaction,
    company_name: str,
    level: int = 1
):

    cursor.execute(
        "SELECT company_name FROM service_companies WHERE company_name=?",
        (company_name,)
    )

    if cursor.fetchone():
        return await interaction.response.send_message(
            "❌ Service company already exists",
            ephemeral=True
        )

    cursor.execute("""
        INSERT INTO service_companies VALUES (?, ?, ?, ?)
    """, (
        company_name,
        interaction.user.id,
        level,
        int(time.time())
    ))

    conn.commit()

    await interaction.response.send_message(
        f"⚖️ Service Company Created\n"
        f"📛 {company_name}\n"
        f"📈 Level: {level}\n"
        f"👤 Owner: {interaction.user.mention}\n"
        f"ℹ️ No production system (service-based)"
    )
def is_company_owner(company_name, user_id):

    cursor.execute(
        "SELECT owner_id FROM industries WHERE company_name=?",
        (company_name,)
    )
    row = cursor.fetchone()

    if row and row[0] == user_id:
        return True

    cursor.execute(
        "SELECT owner_id FROM service_companies WHERE company_name=?",
        (company_name,)
    )
    row = cursor.fetchone()

    return row and row[0]

@bot.tree.command(name="set_tax")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def set_tax(interaction: discord.Interaction, sector: str, rate: float):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only", ephemeral=True)

    if sector not in ["industry", "service"]:
        return await interaction.response.send_message(
            "❌ Use 'industry' or 'service'",
            ephemeral=True
        )

    cursor.execute("""
        INSERT INTO global_taxes VALUES (?, ?)
        ON CONFLICT(tax_type)
        DO UPDATE SET rate=excluded.rate
    """, (sector, rate))

    conn.commit()

    await interaction.response.send_message(
        f"📊 {sector.title()} tax updated to {rate * 100}%"
    )
@bot.tree.command(name="collect_tax")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def collect_tax(interaction: discord.Interaction):

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ Admin only",
            ephemeral=True
        )

    # ================= INDUSTRY TAX =================
    industry_tax = get_tax_rate("industry")

    cursor.execute("SELECT company_name FROM industries")
    industries = cursor.fetchall()

    industry_collected = 0

    for (company,) in industries:

        cursor.execute("""
            SELECT SUM(amount) FROM balances
            WHERE account_name=? AND resource='Cash'
        """, (company,))

        cash = cursor.fetchone()[0] or 0

        tax = int(cash * industry_tax)

        if tax > 0:
            cursor.execute("""
                UPDATE balances
                SET amount = amount - ?
                WHERE account_name=? AND resource='Cash'
            """, (tax, company))

            industry_collected += tax

    # ================= SERVICE TAX =================
    service_tax = get_tax_rate("service")

    cursor.execute("SELECT company_name FROM service_companies")
    services = cursor.fetchall()

    service_collected = 0

    for (company,) in services:

        cursor.execute("""
            SELECT SUM(amount) FROM balances
            WHERE account_name=? AND resource='Cash'
        """, (company,))

        cash = cursor.fetchone()[0] or 0

        tax = int(cash * service_tax)

        if tax > 0:
            cursor.execute("""
                UPDATE balances
                SET amount = amount - ?
                WHERE account_name=? AND resource='Cash'
            """, (tax, company))

            service_collected += tax

    # ================= GIVE TO GOVERNMENT =================
    total = industry_collected + service_collected

    cursor.execute("""
        INSERT INTO balances VALUES ('GOVT_ACCOUNT', 'Cash', ?)
        ON CONFLICT(account_name, resource)
        DO UPDATE SET amount = amount + ?
    """, (total, total))

    conn.commit()

    await interaction.response.send_message(
        f"🏛️ Tax Collected Successfully\n\n"
        f"🏭 Industry Tax: {industry_collected}\n"
        f"⚖️ Service Tax: {service_collected}\n"
        f"💰 Total Collected: {total}"
    )
@bot.tree.command(name="transfer_account_ownership")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def transfer_account_ownership(
    interaction: discord.Interaction,
    account_name: str,
    new_owner: discord.Member
):

    # ---------------- ADMIN CHECK ----------------
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ Admin only",
            ephemeral=True
        )

    # ---------------- CHECK ACCOUNT EXISTS ----------------
    cursor.execute("""
        SELECT owner_id FROM accounts WHERE account_name=?
    """, (account_name,))

    row = cursor.fetchone()

    if not row:
        return await interaction.response.send_message(
            "❌ Account not found",
            ephemeral=True
        )

    old_owner_id = row[0]

    # ---------------- UPDATE OWNER ----------------
    cursor.execute("""
        UPDATE accounts
        SET owner_id=?, holder_name=?
        WHERE account_name=?
    """, (new_owner.id, new_owner.display_name, account_name))

    conn.commit()

    await interaction.response.send_message(
        f"🔄 Ownership Transferred\n\n"
        f"🏦 Account: {account_name}\n"
        f"👤 Old Owner: <@{old_owner_id}>\n"
        f"🆕 New Owner: {new_owner.mention}"
    )
# ---------------- RUN BOT ----------------
bot.run(TOKEN)