import time
import logging
import sqlite3
import datetime
import asyncio
from typing import Optional, List, Tuple, Dict

import discord
from discord.ext import commands, tasks
from discord import app_commands

# ============================================================
# CONFIGURATION
# ============================================================

# !!! KEEP TOKEN EXACTLY AS-IS (PLACEHOLDER) !!!
TOKEN = "MTI3MDM4NDY4NDA3NzE1ODQwMQ.GnqNMv.WzLF5CJ4DP37g1eRCdZ20SRdPXek0Ly77pkY1o"

# Core server
GUILD_ID = 1305582227996016731

# Roles
STAFF_ROLE_ID = 1401899762369822740                 # "Staff" (general)
STAFF_TEAM_ROLE_ID = 1401895531583639582            # Staff Team (future use)
MODERATOR_ROLE_ID = 1391094946143932499             # Moderators (cannot /ban)
ADMIN_ROLE_ID = 1428038351814000671                 # Administrators
SUPER_ADMIN_ROLE_ID = 1390831780348825611           # Highest tier

# Channels
STAFF_LOG_CHANNEL_ID = 1444041573607280872          # General staff logs
BAN_REQUEST_CHANNEL_ID = 1455172941296701450        # /reqban output channel
APPEALS_CHANNEL_ID = 1455122904072323256            # Ban appeals output channel


# Emojis (EXACT per your examples)
EMOJI_OVRP1 = "<:OVRP1:1455159417497583818>"
EMOJI_CHECK = "<:OVCheck:1455159291739635722>"
EMOJI_CROSS = "<:OVCross:1455159223972397212>"
EMOJI_WAIT = "<:OVWait:1455159556790423654>"

# Images (EXACT per your examples)
OVRP_LOGO_URL = (
    "https://media.discordapp.net/attachments/1182810721885618236/"
    "1345161170381963406/OVRPLOGO.jpg?ex=6954fb36&is=6953a9b6&hm="
    "9ea9b8ff7e33235d8a71b10cf517e0321dcecdef5b61564190290c8df06366e8&=&format=webp"
)

APPEAL_AUTHOR_ICON_URL = "https://cdn.discordapp.com/avatars/813734454828072960/a_dd9b23ea40e002ea5ba0438acb3689f8.webp?size=128"
APPEAL_STAFF_FOOTER_ICON_URL = "https://media.discordapp.net/attachments/1182810721885618236/1345161170381963406/OVRPLOGO.jpg?ex=6954fb36&is=6953a9b6&hm=9ea9b8ff7e33235d8a71b10cf517e0321dcecdef5b61564190290c8df06366e8&=&format=webp"

BANNER_IMAGE_URL = (
    "https://media.discordapp.net/attachments/1182810721885618236/"
    "1317299942397579264/abcd.jpg?ex=69547a2c&is=695328ac&hm="
    "46b5278052c886d6c0daa33d7af9844d432227cea97f33fa07ce7b25e273dda6&=&format=webp"
)

# Channels
STAFF_LOG_CHANNEL_ID = 1444041573607280872          # General staff logs
BAN_REQUEST_CHANNEL_ID = 1455172941296701450        # /reqban output channel

# Database
DB_PATH = "moderation.db"

# Simulation toggle
# True  -> fake only, no real bans/kicks/mutes/unbans
# False -> actually performs moderation actions
SIMULATION_MODE = True

# ============================================================
# LOGGING
# ============================================================

logger = logging.getLogger("ovrp_moderation")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# ============================================================
# DATABASE HELPERS
# ============================================================


def get_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    con = get_db()
    cur = con.cursor()

    # Moderation cases
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cases (
            case_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            action_number INTEGER NOT NULL,
            reason TEXT,
            evidence TEXT,
            duration_seconds INTEGER,
            created_at INTEGER NOT NULL,
            expires_at INTEGER,
            automatic INTEGER NOT NULL DEFAULT 0,
            staff_message_id INTEGER,
            auto_unban_done INTEGER NOT NULL DEFAULT 0
        );
        """
    )

    # Ban requests (/reqban)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ban_requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            duration_seconds INTEGER,
            reason TEXT,
            evidence TEXT,
            created_at INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            staff_message_id INTEGER,
            resolved_by_id INTEGER,
            resolved_reason TEXT
        );
        """
    )

    # Ban appeals
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS appeals (
            appeal_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            case_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            roblox_username TEXT NOT NULL,
            q1 TEXT NOT NULL,
            q2 TEXT,
            created_at INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING / ACCEPTED / DENIED
            decided_at INTEGER,
            decided_by_id INTEGER,
            decided_reason TEXT,
            staff_message_id INTEGER,
            user_message_id INTEGER
        );
        """
    )

    con.commit()
    con.close()


def next_action_number(guild_id: int, user_id: int, action: str) -> int:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM cases WHERE guild_id = ? AND user_id = ? AND action = ?",
        (guild_id, user_id, action),
    )
    row = cur.fetchone()
    count = int(row[0]) if row is not None else 0
    con.close()
    return count + 1


def create_case(
    guild_id: int,
    user_id: int,
    moderator_id: int,
    action: str,
    reason: str,
    evidence: str,
    duration_seconds: Optional[int],
    expires_at: Optional[int],
    automatic: bool = False,
) -> Tuple[int, int]:
    created_at = int(time.time())
    action = action.upper()
    action_number = next_action_number(guild_id, user_id, action)
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO cases (
            guild_id, user_id, moderator_id, action, action_number,
            reason, evidence, duration_seconds, created_at,
            staff_message_id, expires_at, auto_unban_done, automatic
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            guild_id,
            user_id,
            moderator_id,
            action,
            action_number,
            reason,
            evidence,
            duration_seconds,
            created_at,
            None,
            expires_at,
            1 if automatic else 0,
        ),
    )
    case_id = int(cur.lastrowid)
    con.commit()
    con.close()
    return case_id, action_number


def set_case_staff_message(case_id: int, message_id: int) -> None:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "UPDATE cases SET staff_message_id = ? WHERE case_id = ?",
        (message_id, case_id),
    )
    con.commit()
    con.close()


def mark_case_auto_unban_done(case_id: int) -> None:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "UPDATE cases SET auto_unban_done = 1 WHERE case_id = ?",
        (case_id,),
    )
    con.commit()
    con.close()


def delete_case(guild_id: int, case_id: int) -> bool:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "DELETE FROM cases WHERE guild_id = ? AND case_id = ?",
        (guild_id, case_id),
    )
    deleted = cur.rowcount > 0
    con.commit()
    con.close()
    return deleted


def fetch_cases_for_user(guild_id: int, user_id: int) -> List[sqlite3.Row]:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        SELECT *
        FROM cases
        WHERE guild_id = ? AND user_id = ?
        ORDER BY case_id ASC
        """,
        (guild_id, user_id),
    )
    rows = cur.fetchall()
    con.close()
    return list(rows)


def fetch_counts_for_user(guild_id: int, user_id: int) -> Dict[str, int]:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        SELECT action, COUNT(*) as c
        FROM cases
        WHERE guild_id = ? AND user_id = ?
        GROUP BY action
        """,
        (guild_id, user_id),
    )
    rows = cur.fetchall()
    con.close()

    result: Dict[str, int] = {
        "BAN": 0,
        "MUTE": 0,
        "WARN": 0,
        "KICK": 0,
        "UNMUTE": 0,
        "UNBAN": 0,
        "total": 0,
    }
    for row in rows:
        action = str(row["action"]).upper()
        count = int(row["c"])
        if action in result:
            result[action] = count
        result["total"] += count
    return result


def fetch_expired_bans(now_ts: int) -> List[sqlite3.Row]:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        SELECT *
        FROM cases
        WHERE action = 'BAN'
          AND expires_at IS NOT NULL
          AND expires_at <= ?
          AND auto_unban_done = 0
        """,
        (now_ts,),
    )
    rows = cur.fetchall()
    con.close()
    return list(rows)


# --------- Ban request DB helpers (/reqban) ---------


def create_ban_request(
    guild_id: int,
    target_id: int,
    moderator_id: int,
    duration_seconds: Optional[int],
    reason: str,
    evidence: str,
) -> int:
    created_at = int(time.time())
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO ban_requests (
            guild_id, target_id, moderator_id, duration_seconds,
            reason, evidence, created_at, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')
        """,
        (guild_id, target_id, moderator_id, duration_seconds, reason, evidence, created_at),
    )
    req_id = int(cur.lastrowid)
    con.commit()
    con.close()
    return req_id


def set_ban_request_message(request_id: int, message_id: int) -> None:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "UPDATE ban_requests SET staff_message_id = ? WHERE request_id = ?",
        (message_id, request_id),
    )
    con.commit()
    con.close()


def get_ban_request(request_id: int) -> Optional[sqlite3.Row]:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM ban_requests WHERE request_id = ?",
        (request_id,),
    )
    row = cur.fetchone()
    con.close()
    return row


def update_ban_request_status(
    request_id: int,
    status: str,
    resolved_by_id: int,
    resolved_reason: Optional[str],
) -> None:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        UPDATE ban_requests
        SET status = ?, resolved_by_id = ?, resolved_reason = ?
        WHERE request_id = ?
        """,
        (status, resolved_by_id, resolved_reason, request_id),
    )
    con.commit()
    con.close()

# --------- Appeal DB helpers ---------


def create_appeal(
    guild_id: int,
    case_id: int,
    user_id: int,
    roblox_username: str,
    q1: str,
    q2: str,
) -> int:
    created_at = int(time.time())
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO appeals (
            guild_id, case_id, user_id,
            roblox_username, q1, q2, created_at, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')
        """,
        (guild_id, case_id, user_id, roblox_username, q1, q2, created_at),
    )
    appeal_id = int(cur.lastrowid)
    con.commit()
    con.close()
    return appeal_id


def get_appeal(appeal_id: int) -> Optional[sqlite3.Row]:
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM appeals WHERE appeal_id = ?", (appeal_id,))
    row = cur.fetchone()
    con.close()
    return row


def set_appeal_staff_message(appeal_id: int, message_id: int) -> None:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "UPDATE appeals SET staff_message_id = ? WHERE appeal_id = ?",
        (message_id, appeal_id),
    )
    con.commit()
    con.close()


def set_appeal_user_message(appeal_id: int, message_id: int) -> None:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "UPDATE appeals SET user_message_id = ? WHERE appeal_id = ?",
        (message_id, appeal_id),
    )
    con.commit()
    con.close()


def update_appeal_status(
    appeal_id: int,
    status: str,
    decided_by_id: int,
    decided_reason: Optional[str],
) -> None:
    decided_at = int(time.time())
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        UPDATE appeals
        SET status = ?, decided_at = ?, decided_by_id = ?, decided_reason = ?
        WHERE appeal_id = ?
        """,
        (status, decided_at, decided_by_id, decided_reason, appeal_id),
    )
    con.commit()
    con.close()

def fetch_case_by_id(case_id: int) -> Optional[sqlite3.Row]:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM cases WHERE case_id = ?",
        (case_id,),
    )
    row = cur.fetchone()
    con.close()
    return row


def get_last_case_action(guild_id: int, user_id: int) -> Optional[str]:
    """
    Returns the action of the most recent case for this user (BAN, MUTE, UNBAN, etc.)
    """
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        SELECT action
        FROM cases
        WHERE guild_id = ? AND user_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (guild_id, user_id),
    )
    row = cur.fetchone()
    con.close()
    return str(row["action"]).upper() if row else None


def has_active_ban(guild_id: int, user_id: int) -> bool:
    """
    Treats a user as 'actively banned' if their latest case is a BAN.
    Any UNBAN (manual or automatic) will flip this.
    """
    return get_last_case_action(guild_id, user_id) == "BAN"


def has_active_mute(guild_id: int, user_id: int) -> bool:
    """
    Treats a user as 'actively muted' if their latest case is a MUTE.
    Any UNMUTE will flip this.
    """
    return get_last_case_action(guild_id, user_id) == "MUTE"


def get_active_appeal_for_case(
    guild_id: int,
    case_id: int,
    user_id: int,
) -> Optional[sqlite3.Row]:
    """
    Returns latest PENDING appeal for this case/user (if any).
    """
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        SELECT *
        FROM appeals
        WHERE guild_id = ?
          AND case_id = ?
          AND user_id = ?
          AND status = 'PENDING'
        ORDER BY appeal_id DESC
        LIMIT 1
        """,
        (guild_id, case_id, user_id),
    )
    row = cur.fetchone()
    con.close()
    return row

def has_accepted_appeal_for_case(
    guild_id: int,
    case_id: int,
    user_id: int,
) -> bool:
    """Return True if this ban already has an ACCEPTED appeal."""
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        SELECT 1
        FROM appeals
        WHERE guild_id = ?
          AND case_id = ?
          AND user_id = ?
          AND status = 'ACCEPTED'
        LIMIT 1
        """,
        (guild_id, case_id, user_id),
    )
    row = cur.fetchone()
    con.close()
    return row is not None


# ============================================================
# UTILITY HELPERS
# ============================================================


def discord_timestamp(ts: int, style: str = "f") -> str:
    return f"<t:{int(ts)}:{style}>"


def join_evidence(url: Optional[str], attachment: Optional[discord.Attachment]) -> str:
    parts: List[str] = []
    if url:
        u = url.strip()
        if u:
            parts.append(u)
    if attachment:
        parts.append(attachment.url)
    return " ".join(parts) if parts else "N/A"


def is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(role.id == STAFF_ROLE_ID for role in member.roles)


def is_moderator(member: discord.Member) -> bool:
    return any(role.id == MODERATOR_ROLE_ID for role in member.roles)


def is_admin(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    admin_ids = {ADMIN_ROLE_ID, SUPER_ADMIN_ROLE_ID}
    return any(role.id in admin_ids for role in member.roles)

async def is_currently_banned(guild: discord.Guild, user_id: int) -> bool:
    """
    Returns True if the user is currently banned from the guild (Discord-side).
    """
    try:
        await guild.fetch_ban(discord.Object(id=user_id))
        return True
    except discord.NotFound:
        return False
    except discord.Forbidden:
        # Can't read bans; don't hard-block staff
        return False


def is_currently_timed_out(member: discord.Member) -> bool:
    """
    Returns True if the member currently has an active communication timeout.
    """
    if hasattr(member, "is_timed_out") and callable(member.is_timed_out):
        try:
            return member.is_timed_out()
        except Exception:
            pass

    until = getattr(member, "communication_disabled_until", None)
    if until is None:
        return False
    if isinstance(until, datetime.datetime):
        now = datetime.datetime.now(datetime.timezone.utc)
        return until.replace(tzinfo=datetime.timezone.utc) > now
    return False


async def send_error(
    interaction: discord.Interaction,
    code: int,
    message: str,
    ephemeral: bool = True,
) -> None:
    embed = (
        discord.Embed(
            color=0xE74C3C,
            title=f"{EMOJI_CROSS} Error {code}",
            description=message,
        )
        .set_author(name="OVRP | Error", icon_url=OVRP_LOGO_URL)
        .set_footer(text="If this keeps happening, contact a server administrator.")
    )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except Exception as e:
        logger.warning("Failed to send error response: %s", e)


def duration_days_to_seconds(days: int) -> int:
    return int(days) * 24 * 60 * 60


def duration_hours_to_seconds(hours: int) -> int:
    return int(hours) * 60 * 60


def format_action_summary(row: sqlite3.Row) -> str:
    action = str(row["action"]).upper()
    secs = int(row["duration_seconds"] or 0)
    if action == "BAN":
        if secs > 0:
            days = secs // (24 * 60 * 60)
            return f"Banned for {days} day(s)"
        return "Banned permanently"
    if action == "KICK":
        return "Kicked"
    if action == "WARN":
        return "Warned"
    if action == "MUTE":
        if secs > 0:
            hours = secs // 3600
            return f"Muted for {hours} hour(s)"
        return "Muted"
    if action == "UNMUTE":
        return "Unmuted"
    if action == "UNBAN":
        return row["reason"]
    return action.title()


def build_case_block(guild_id: int, row: sqlite3.Row) -> str:
    case_id = int(row["case_id"])
    action = str(row["action"]).upper()
    number = int(row["action_number"])
    created_at = int(row["created_at"])
    moderator_id = int(row["moderator_id"])
    reason = row["reason"] or "No reason provided."
    evidence = row["evidence"] or "N/A"
    summary = format_action_summary(row)

    staff_message_id = row["staff_message_id"]
    if staff_message_id:
        url = f"https://discord.com/channels/{guild_id}/{STAFF_LOG_CHANNEL_ID}/{int(staff_message_id)}"
        case_label = f"[Case #{case_id}]({url})"
    else:
        case_label = f"Case #{case_id}"

    header = f"**{case_label}** & {action.title()} {number} | {summary}"
    ts_str = discord_timestamp(created_at, "f")
    lines = [
        header,
        f"Date: {ts_str}",
        f"Moderator: <@{moderator_id}> (`{moderator_id}`)",
        f"Reason: {reason}",
        "",
        "> Evidence:",
        f"> {evidence}",
    ]
    return "\n".join(lines)


def build_confirm_embed(
    *,
    action_label: str,
    case_id: int,
    action_number: int,
    member: discord.abc.User,
    log_url: str,
    duration_text: Optional[str] = None,
) -> discord.Embed:
    desc = (
        f"{EMOJI_CHECK} **Moderation action completed and logged.**\n\n"
        f"**Member:** <@{member.id}> (`{member.id}`)\n"
        f"**Action:** {action_label}\n"
    )
    if duration_text:
        desc += f"**Duration:** {duration_text}"

    embed = discord.Embed(
        color=0x2ECC71,
        title=f"{EMOJI_OVRP1} Moderation Action | Case #{case_id} & {action_label} {action_number}",
        url=log_url,
        description=desc,
    )
    embed.set_author(name="OVRP | Moderation System", icon_url=OVRP_LOGO_URL)
    embed.set_footer(
        text="This action has been applied in accordance with OVRP moderation guidelines.",
    )
    return embed

from typing import Tuple  # already imported at top in your file

def build_ban_dm_embed_and_view(
    *,
    case_id: int,
    ban_number: int,
    member: discord.abc.User,
    reason: str,
    evidence_text: str,
    duration_label: str,
    duration_seconds: int,
    created_at: int,
) -> Tuple[discord.Embed, Optional[discord.ui.View]]:
    dm_embed = (
        discord.Embed(
            color=0xE74C3C,
            title=f"{EMOJI_OVRP1} Moderation Action Issued",
            description=(
                f"You have been banned from **OVRP | Oceanview Roleplay** | **Ban {ban_number}**\n"
            ),
        )
        .set_author(
            name="OVRP | Moderation Notice",
            icon_url=OVRP_LOGO_URL,
        )
        .set_image(url=BANNER_IMAGE_URL)
        .set_footer(
            text=(
                f"Case #{case_id} | You may submit an appeal if you believe this decision was incorrect"
            ),
        )
    )
    dm_embed.add_field(
        name="Duration",
        value=duration_label,
        inline=True,
    )
    dm_embed.add_field(
        name="Evidence",
        value=evidence_text,
        inline=True,
    )
    dm_embed.add_field(
        name="Reason",
        value=reason,
        inline=False,
    )

    view: Optional[discord.ui.View] = None
    # 0 = permanent; > 4 days = appealable
    if duration_seconds == 0 or duration_seconds > 4 * 24 * 60 * 60:
        view = BanAppealView(
            case_id=case_id,
            user_id=member.id,
            duration_seconds=duration_seconds,
            created_at=created_at,
        )

    return dm_embed, view


# ============================================================
# DISCORD BOT SETUP
# ============================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    logger.info("Logged in as %s (%s)", bot.user, bot.user.id)  # type: ignore
    try:
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()

        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        logger.info("Synced %d command(s) to guild %s", len(synced), GUILD_ID)
    except Exception as e:
        logger.exception("Failed to sync commands: %s", e)


# ============================================================
# UI COMPONENTS (VIEWS & MODALS)
# ============================================================


class DeleteCaseModal(discord.ui.Modal, title="Delete a Case"):
    def __init__(self, guild_id: int, original_view: "ModlogsView"):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.original_view = original_view
        self.case_id_input = discord.ui.TextInput(
            label="Case ID to delete",
            placeholder="Enter the Case ID number (e.g. 12)",
            required=True,
            max_length=10,
        )
        self.add_item(self.case_id_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.user or not isinstance(interaction.user, discord.Member):
            await send_error(interaction, 401, "You must be in the server to delete a case.")
            return
        if interaction.user.id != self.original_view.owner_id:
            await send_error(
                interaction,
                403,
                "You can only manage cases from modlogs you opened.",
            )
            return
        if not is_admin(interaction.user):
            await send_error(
                interaction,
                500,
                "You do not have permission to delete moderation cases.",
            )
            return

        try:
            case_id = int(str(self.case_id_input.value).strip())
        except ValueError:
            await send_error(interaction, 400, "Case ID must be a valid number.")
            return

        deleted = delete_case(self.guild_id, case_id)
        if not deleted:
            await send_error(
                interaction,
                404,
                f"Case ID #{case_id} does not exist or is not from this server.",
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=False)
        await self.original_view.refresh_after_delete(interaction)
        await interaction.followup.send(
            content=f"{EMOJI_CHECK} Case `#{case_id}` has been deleted.",
            ephemeral=True,
        )


class ModlogsView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        target: discord.Member | discord.User,
        entries: List[sqlite3.Row],
        owner_id: int,
        current_page: int = 0,
    ):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.target = target
        self.entries = entries
        self.current_page = current_page
        self.per_page = 4
        self.mode = "logs"  # "logs" or "overview"
        self.owner_id = owner_id
        self.update_button_states()

    @property
    def max_page(self) -> int:
        if not self.entries:
            return 0
        return max((len(self.entries) - 1) // self.per_page, 0)

    def _page_slice(self) -> Tuple[int, int]:
        start = self.current_page * self.per_page
        end = start + self.per_page
        return start, end

    def _page_entries(self) -> List[sqlite3.Row]:
        start, end = self._page_slice()
        return self.entries[start:end]

    def update_button_states(self) -> None:
        total_pages = self.max_page + 1 if self.entries else 1
        for child in self.children:
            if not isinstance(child, discord.ui.Button):
                continue
            label = child.label
            if label in ("⏮️", "◀️"):
                child.disabled = (
                    self.mode == "overview"
                    or self.current_page == 0
                    or total_pages <= 1
                )
            elif label in ("▶️", "⏭️"):
                child.disabled = (
                    self.mode == "overview"
                    or self.current_page >= self.max_page
                    or total_pages <= 1
                )
            elif label == "View Overview":
                child.disabled = self.mode == "overview"
            elif label == "View Modlogs":
                child.disabled = self.mode == "logs"

    def create_embed(self) -> discord.Embed:
        total_logs = len(self.entries)
        start, end = self._page_slice()
        page_entries = self._page_entries()

        if isinstance(self.target, discord.Member):
            avatar_url = self.target.display_avatar.url
            display_name = self.target.display_name
        else:
            avatar_url = self.target.display_avatar.url
            display_name = getattr(self.target, "display_name", self.target.name)

        embed = discord.Embed(color=0x3498DB)
        embed.set_author(
            name=f"{display_name} | {total_logs} log(s)",
            icon_url=avatar_url,
        )
        embed.title = f"{display_name}'s Moderation History"

        if page_entries:
            blocks = [build_case_block(self.guild_id, row) for row in page_entries]
            embed.description = "\n\n".join(blocks)
        else:
            embed.description = "No moderation history found for this user."

        now_ts = int(time.time())
        now_dt = datetime.datetime.fromtimestamp(now_ts, datetime.timezone.utc)
        now_str = now_dt.strftime("%d %B %Y at %H:%M")

        footer_text = (
            f"Logs {start + 1}-{min(end, total_logs)} of {total_logs} | "
            f"Page {self.current_page + 1}/{self.max_page + 1 if total_logs else 1} | "
            f"ID: {self.target.id} | {now_str}"
        )
        embed.set_footer(text=footer_text)
        return embed

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if not interaction.user or interaction.user.id != self.owner_id:
            await send_error(
                interaction,
                403,
                "Only the staff member who opened this view can use these buttons.",
            )
            return False
        return True

    async def refresh_after_delete(self, interaction: discord.Interaction) -> None:
        self.entries = fetch_cases_for_user(self.guild_id, self.target.id)
        if self.current_page > self.max_page:
            self.current_page = self.max_page
        self.mode = "logs"
        self.update_button_states()
        embed = self.create_embed()
        try:
            await interaction.message.edit(embed=embed, view=self)  # type: ignore
        except Exception as e:
            logger.warning("Failed to refresh modlogs message after delete: %s", e)

    @discord.ui.button(label="⏮️", style=discord.ButtonStyle.secondary)
    async def first_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._check_owner(interaction):
            return
        self.mode = "logs"
        self.current_page = 0
        self.update_button_states()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def prev_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._check_owner(interaction):
            return
        self.mode = "logs"
        self.current_page = max(self.current_page - 1, 0)
        self.update_button_states()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._check_owner(interaction):
            return
        self.mode = "logs"
        self.current_page = min(self.current_page + 1, self.max_page)
        self.update_button_states()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary)
    async def last_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._check_owner(interaction):
            return
        self.mode = "logs"
        self.current_page = self.max_page
        self.update_button_states()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Delete", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete_case_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._check_owner(interaction):
            return
        if not isinstance(interaction.user, discord.Member):
            await send_error(interaction, 401, "You must be in the server to delete cases.")
            return
        if not is_admin(interaction.user):
            await send_error(
                interaction,
                500,
                "You do not have permission to delete moderation cases.",
            )
            return
        modal = DeleteCaseModal(self.guild_id, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="View Overview", style=discord.ButtonStyle.primary)
    async def view_overview(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._check_owner(interaction):
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(
            interaction.user
        ):
            await send_error(interaction, 500, "Only staff members can view overviews.")
            return

        guild = interaction.guild
        if guild is None:
            await send_error(interaction, 500, "This command can only be used in a server.")
            return

        if isinstance(self.target, discord.Member):
            member: Optional[discord.Member] = self.target
        else:
            member = guild.get_member(self.target.id)

        counts = fetch_counts_for_user(self.guild_id, self.target.id)

        if member is not None:
            joined_at = member.joined_at
            roles = [r for r in member.roles if r != guild.default_role]
            role_count = len(roles)
            joined_str = (
                datetime.datetime.fromtimestamp(
                    int(joined_at.timestamp()), datetime.timezone.utc
                ).strftime("%d %B %Y at %H:%M")
                if joined_at
                else "Unknown"
            )
        else:
            joined_str = "Unknown"
            role_count = 0

        created_at_dt = self.target.created_at
        created_str = datetime.datetime.fromtimestamp(
            int(created_at_dt.timestamp()), datetime.timezone.utc
        ).strftime("%d %B %Y at %H:%M")

        overview = discord.Embed(color=0x5865F2)
        overview.set_author(
            name=f"{getattr(self.target, 'display_name', self.target.name)}'s Moderation Overview",  # type: ignore
            icon_url=self.target.display_avatar.url,
        )
        overview.add_field(
            name="User Information",
            value=(
                f"**Mention:** <@{self.target.id}>\n"
                f"**Username:** {self.target.name}\n"
                f"**Display Name:** {getattr(self.target, 'display_name', self.target.name)}\n"
                f"**Joined Server:** {joined_str}\n"
                f"**Account Created:** {created_str}\n"
                f"**Role Count:** {role_count}"
            ),
            inline=False,
        )
        overview.add_field(
            name="Moderation Information",
            value=(
                f"**Bans:** {counts['BAN']}\n"
                f"**Mutes:** {counts['MUTE']}\n"
                f"**Warns:** {counts['WARN']}\n"
                f"**Kicks:** {counts['KICK']}"
            ),
            inline=False,
        )

        now_ts = int(time.time())
        now_dt = datetime.datetime.fromtimestamp(now_ts, datetime.timezone.utc)
        now_str = now_dt.strftime("%d %B %Y at %H:%M")
        overview.set_footer(
            text=f"ID: {self.target.id} | {now_str}"
        )

        self.mode = "overview"
        self.update_button_states()
        await interaction.response.edit_message(embed=overview, view=self)

    @discord.ui.button(label="View Modlogs", style=discord.ButtonStyle.primary)
    async def view_modlogs(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._check_owner(interaction):
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(
            interaction.user
        ):
            await send_error(interaction, 500, "Only staff members can view modlogs.")
            return

        self.mode = "logs"
        self.update_button_states()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)


# --------- /reqban views & modal ---------


class ReqBanDenyModal(discord.ui.Modal, title="Deny Ban Request"):
    def __init__(self, request_id: int):
        super().__init__(timeout=300)
        self.request_id = request_id
        self.reason_input = discord.ui.TextInput(
            label="Reason for denial",
            placeholder="Explain why this ban request is being denied.",
            required=True,
            max_length=300,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        row = get_ban_request(self.request_id)
        if row is None:
            await send_error(
                interaction,
                404,
                "This ban request no longer exists.",
            )
            return

        if not isinstance(interaction.user, discord.Member) or not is_admin(
            interaction.user
        ):
            await send_error(
                interaction,
                500,
                "Only administrators can deny ban requests.",
            )
            return

        if row["status"] != "PENDING":
            await send_error(
                interaction,
                409,
                "This ban request has already been processed.",
            )
            return

        deny_reason = str(self.reason_input.value).strip()
        update_ban_request_status(
            self.request_id,
            "DENIED",
            interaction.user.id,
            deny_reason,
        )

        guild_id = int(row["guild_id"])
        moderator_id = int(row["moderator_id"])
        target_id = int(row["target_id"])
        staff_message_id = int(row["staff_message_id"] or 0)
        title_id = f"req-{self.request_id:03d}"

        # Embed reply in reqban channel pinging the requester
        channel = interaction.client.get_channel(BAN_REQUEST_CHANNEL_ID)
        if isinstance(
            channel,
            (discord.TextChannel, discord.Thread, discord.ForumChannel),
        ) and staff_message_id:
            try:
                msg = await channel.fetch_message(staff_message_id)
                request_url = (
                    f"https://discord.com/channels/{guild_id}/"
                    f"{BAN_REQUEST_CHANNEL_ID}/{staff_message_id}"
                )
                deny_embed = (
                    discord.Embed(
                        color=0xE74C3C,
                        title=f"{EMOJI_OVRP1} Ban request denied | ID: {title_id}",
                        url=request_url,
                        description=(
                            f"{interaction.user.mention} has **denied** this ban request.\n\n"
                            f"**Requester:** <@{moderator_id}> (`{moderator_id}`)\n"
                            f"**Target:** <@{target_id}> (`{target_id}`)\n"
                            f"**Reason:** {deny_reason}"
                        ),
                    )
                    .set_author(
                        name="OVRP | Moderation System",
                        icon_url=OVRP_LOGO_URL,
                    )
                )
                await msg.reply(
                    content=f"<@{moderator_id}>",
                    embed=deny_embed,
                )

                # Disable buttons and turn the main request embed red
                try:
                    view = msg.components  # legacy; easier just to nuke view
                except Exception:
                    view = None

                if msg.embeds:
                    base = msg.embeds[0]
                    base.color = discord.Color(0xE74C3C)
                    await msg.edit(embed=base, view=None)
                else:
                    await msg.edit(view=None)

            except Exception as e:
                logger.warning("Failed to reply under ban request message: %s", e)

        # Ephemeral confirmation to the admin
        admin_embed = (
            discord.Embed(
                color=0xE74C3C,
                title=f"{EMOJI_CROSS} Ban request denied",
                description=(
                    f"Ban request `{title_id}` has been denied.\n"
                    f"Reason: {deny_reason}"
                ),
            )
            .set_author(
                name="OVRP | Moderation System",
                icon_url=OVRP_LOGO_URL,
            )
        )
        await interaction.response.send_message(
            embed=admin_embed,
            ephemeral=True,
        )


class ReqBanView(discord.ui.View):
    def __init__(self, request_id: int):
        super().__init__(timeout=None)
        self.request_id = request_id

    async def _get_request_and_check_admin(
        self, interaction: discord.Interaction
    ) -> Optional[sqlite3.Row]:
        if not isinstance(interaction.user, discord.Member) or not is_admin(
            interaction.user
        ):
            await send_error(
                interaction,
                500,
                "Only administrators can approve or deny ban requests.",
            )
            return None

        row = get_ban_request(self.request_id)
        if row is None:
            await send_error(
                interaction,
                404,
                "This ban request no longer exists.",
            )
            return None

        if row["status"] != "PENDING":
            await send_error(
                interaction,
                409,
                "This ban request has already been processed.",
            )
            return None

        return row

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        row = await self._get_request_and_check_admin(interaction)
        if row is None:
            return

        guild = interaction.guild
        if guild is None:
            await send_error(
                interaction,
                500,
                "This can only be used inside the server.",
            )
            return

        target_id = int(row["target_id"])
        moderator_id = int(row["moderator_id"])
        duration_seconds = int(row["duration_seconds"] or 0)
        reason = row["reason"]
        evidence = row["evidence"]
        staff_message_id = int(row["staff_message_id"] or 0)
        title_id = f"req-{self.request_id:03d}"

        update_ban_request_status(
            self.request_id,
            "APPROVED",
            interaction.user.id,
            "Approved",
        )

        now_ts = int(time.time())
        expires_at = now_ts + duration_seconds if duration_seconds > 0 else None
        case_id, ban_number = create_case(
            guild.id,
            target_id,
            moderator_id,
            "BAN",
            reason,
            evidence,
            duration_seconds if duration_seconds > 0 else None,
            expires_at,
            automatic=False,
        )

        duration_label = (
            f"{duration_seconds // (24 * 60 * 60)} day(s)"
            if duration_seconds > 0
            else "Permanent"
        )
        created_at = now_ts
        ts_str = discord_timestamp(created_at, "f")

        staff_embed = (
            discord.Embed(
                color=0xE74C3C,
                title=f"{EMOJI_OVRP1} Ban | Case #{case_id} & Ban {ban_number}",
                timestamp=datetime.datetime.utcfromtimestamp(created_at),
            )
            .set_author(
                name="OVRP | Moderation System",
                icon_url=OVRP_LOGO_URL,
            )
            .set_footer(text="OVRP | Moderation Systems")
        )
        staff_embed.add_field(
            name="Member",
            value=f"<@{target_id}> (`{target_id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Moderator",
            value=f"<@{moderator_id}> (`{moderator_id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Requested By",
            value=f"<@{moderator_id}> (`{moderator_id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Approved By",
            value=f"<@{interaction.user.id}> (`{interaction.user.id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Request ID",
            value=f"`{title_id}`",
            inline=True,
        )
        staff_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        staff_embed.add_field(
            name="Evidence",
            value=evidence,
            inline=True,
        )
        staff_embed.add_field(
            name="Duration",
            value=duration_label,
            inline=True,
        )
        staff_embed.add_field(
            name="Date",
            value=ts_str,
            inline=True,
        )

        staff_channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
        if not isinstance(
            staff_channel,
            (discord.TextChannel, discord.Thread, discord.ForumChannel),
        ):
            await send_error(
                interaction,
                503,
                "Staff log channel is misconfigured. Please contact an administrator.",
            )
            return

        try:
            msg = await staff_channel.send(embed=staff_embed)
        except discord.Forbidden:
            await send_error(
                interaction,
                500,
                "I do not have permission to send messages in the staff log channel.",
            )
            return
        except discord.HTTPException:
            await send_error(
                interaction,
                520,
                "Failed to post to the staff log channel due to an unknown error.",
            )
            return

        set_case_staff_message(case_id, msg.id)
        log_url = f"https://discord.com/channels/{guild.id}/{STAFF_LOG_CHANNEL_ID}/{msg.id}"

        # DM banned user (same style as /ban)
        target_user: Optional[discord.abc.User] = None
        try:
            target_user = await bot.fetch_user(target_id)
        except Exception:
            target_user = None

        dm_embed = (
            discord.Embed(
                color=0xE74C3C,
                title=f"{EMOJI_OVRP1} Moderation Action Issued",
                description=(
                    f"You have been banned from **OVRP | Oceanview Roleplay** | **Ban {ban_number}**\n"
                ),
            )
            .set_author(
                name="OVRP | Moderation Notice",
                icon_url=OVRP_LOGO_URL,
            )
            .set_image(url=BANNER_IMAGE_URL)
            .set_footer(
                text=f"Case #{case_id} | You may submit an appeal if you believe this decision was incorrect",
            )
        )
        dm_embed.add_field(
            name="Duration",
            value=duration_label,
            inline=True,
        )
        dm_embed.add_field(
            name="Evidence",
            value=evidence,
            inline=True,
        )
        dm_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )

        dm_view: Optional[discord.ui.View] = None
        # Only show appeal button for perm or > 4 day bans
        if duration_seconds == 0 or (duration_seconds // (24 * 60 * 60)) > 4:
            dm_view = BanAppealView(
                case_id=case_id,
                user_id=target_id,
                duration_seconds=duration_seconds,
                created_at=now_ts,
            )

        if target_user is not None:
            try:
                if dm_view:
                    await target_user.send(embed=dm_embed, view=dm_view)
                else:
                    await target_user.send(embed=dm_embed)
            except Exception:
                pass

        if not SIMULATION_MODE:
            try:
                await guild.ban(
                    discord.Object(id=target_id),
                    reason=f"[Case #{case_id}] {reason}",
                    delete_message_days=0,
                )
            except discord.Forbidden:
                await send_error(
                    interaction,
                    500,
                    "I do not have permission to ban this member.",
                )
                return
            except discord.HTTPException:
                await send_error(
                    interaction,
                    520,
                    "Failed to ban this member due to an unknown error.",
                )
                return

        # Disable buttons after processing
        button.disabled = True  # type: ignore
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        # Turn the original request embed green (approved)
        try:
            if interaction.message and interaction.message.embeds:
                base = interaction.message.embeds[0]
                base.color = discord.Color(0x2ECC71)
                await interaction.message.edit(embed=base, view=self)  # type: ignore
            else:
                await interaction.message.edit(view=self)  # type: ignore
        except Exception:
            pass


        # Embed in reqban channel pinging the requester
        if interaction.message and staff_message_id:
            channel_embed = (
                discord.Embed(
                    color=0x2ECC71,
                    title=f"{EMOJI_OVRP1} Ban request approved | ID: {title_id}",
                    url=log_url,
                    description=(
                        f"Your ban request for <@{target_id}> has been **approved** and processed.\n\n"
                        f"**Case:** `#{case_id}` | **Ban `{ban_number}`\n"
                        f"**Approved By:** <@{interaction.user.id}> (`{interaction.user.id}`)"
                    ),
                )
                .set_author(
                    name="OVRP | Moderation System",
                    icon_url=OVRP_LOGO_URL,
                )
            )
            try:
                await interaction.message.reply(
                    content=f"<@{moderator_id}>",
                    embed=channel_embed,
                )
            except Exception as e:
                logger.warning("Failed to reply in reqban channel: %s", e)

        # Ephemeral confirmation for the admin
        admin_embed = (
            discord.Embed(
                color=0x2ECC71,
                title=f"{EMOJI_CHECK} Ban request approved",
                description=(
                    f"Ban request `{title_id}` has been approved and processed.\n"
                    f"Case `#{case_id}` • Ban {ban_number}"
                ),
            )
            .set_author(
                name="OVRP | Moderation System",
                icon_url=OVRP_LOGO_URL,
            )
        )
        await interaction.response.send_message(
            embed=admin_embed,
            ephemeral=True,
        )

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        row = await self._get_request_and_check_admin(interaction)
        if row is None:
            return

        modal = ReqBanDenyModal(self.request_id)
        await interaction.response.send_modal(modal)

class ModerationAppealModal(discord.ui.Modal, title="Submit an Appeal"):
    roblox_username = discord.ui.TextInput(
        label="Roblox Username",
        placeholder="Enter your Roblox username",
        required=True,
        max_length=40,
    )
    q1 = discord.ui.TextInput(
        label="Why do you believe this ban was incorrect?",
        style=discord.TextStyle.paragraph,
        max_length=900,
        required=True,
    )
    q2 = discord.ui.TextInput(
        label="Anything else we should know? (optional)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=900,
    )

    def __init__(self, case_id: int, user_id: int):
        super().__init__()
        self.case_id = int(case_id)
        self.user_id = int(user_id)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.client.get_guild(GUILD_ID)
        if guild is None:
            await send_error(
                interaction,
                500,
                "The appeal system is currently unavailable. Please try again later.",
            )
            return

        if interaction.user.id != self.user_id:
            await send_error(
                interaction,
                403,
                "Only the affected user can appeal this case.",
            )
            return

        case = fetch_case_by_id(self.case_id)
        if not case or int(case["guild_id"]) != guild.id or int(case["user_id"]) != self.user_id:
            await send_error(
                interaction,
                404,
                "This case could not be found.",
            )
            return

        if str(case["action"]).upper() != "BAN":
            await send_error(
                interaction,
                400,
                "Only bans can be appealed.",
            )
            return

        # Check that no pending appeal already exists
        # Block if an appeal for this ban has already been accepted
        if has_accepted_appeal_for_case(guild.id, self.case_id, self.user_id):
            await send_error(
                interaction,
                409,
                "This ban appeal has already been accepted. You cannot submit another appeal for this case.",
            )
            return

        # Check that no pending appeal already exists
        existing = get_active_appeal_for_case(guild.id, self.case_id, self.user_id)
        if existing is not None:
            await send_error(
                interaction,
                409,
                "There is already an active appeal open for this ban.",
            )
            return

        # Save appeal
        appeal_id = create_appeal(
            guild.id,
            self.case_id,
            self.user_id,
            str(self.roblox_username),
            str(self.q1),
            str(self.q2 or "").strip(),
        )

        created_at = int(time.time())
        ts_str = discord_timestamp(created_at, "f")
        appeal_code = f"A-{appeal_id:03d}"

        # === DM confirmation to user ===
        user_embed = (
            discord.Embed(
                color=15844367,
                title=f"📩 Appeal submitted | ID: {appeal_code}",
                description=(
                    "Your ban appeal for **OVRP | Oceanview Roleplay** has been submitted.\n"
                    f"{EMOJI_WAIT} It may take **up to 72 hours** for staff to review it.\n"
                ),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            .set_author(
                name="Appeal Confirmation",
                icon_url=APPEAL_AUTHOR_ICON_URL,
            )
            .set_image(url=BANNER_IMAGE_URL)
            .set_footer(
                text="If your appeal has not received a response within 72 hours, please DM a member of the OVRP Managemet Team for further review. ",
            )
        )

        try:
            dm_msg = await interaction.user.send(embed=user_embed)
            set_appeal_user_message(appeal_id, dm_msg.id)
        except Exception:
            # ignore DM failure
            pass

        # === Staff embed in appeals channel ===
        case_created = int(case["created_at"])
        ban_number = int(case["action_number"])
        reason = case["reason"] or "No reason provided."
        evidence = case["evidence"] or "N/A"
        duration_secs = int(case["duration_seconds"] or 0)
        duration_label = (
            f"{duration_secs // (24 * 60 * 60)} day(s)" if duration_secs > 0 else "Permanent"
        )
        stats = fetch_counts_for_user(guild.id, self.user_id)
        stats_line = (
            f"Bans **{stats['BAN']}** | "
            f"Mutes **{stats['MUTE']}** | "
            f"Warns **{stats['WARN']}** | "
            f"Kicks **{stats['KICK']}**"
        )

        case_staff_message_id = case["staff_message_id"]
        if case_staff_message_id:
            case_url = (
                f"https://discord.com/channels/{guild.id}/"
                f"{STAFF_LOG_CHANNEL_ID}/{int(case_staff_message_id)}"
            )
            case_label = f"[Case #{self.case_id}]({case_url})"
        else:
            case_label = f"Case #{self.case_id}"

        staff_embed = (
            discord.Embed(
                color=3499726,
                url=case_url if case_url else "https://roblox.com",
                title=f"{EMOJI_OVRP1} OVRP | Ban Appeal Case #{self.case_id}",
                description=(
                    f"<@{self.user_id}> has submitted an appeal for a moderation case.\n"
                    f"**Appeal ID Reference:** `{appeal_code}`\n\n"
                    "**`ℹ️` Applicant Details:**\n"
                    f"**Username:** <@{self.user_id}>\n"
                    f"**ROBLOX Username:** {self.roblox_username}\n"
                    f"**History:** Bans: `{stats['BAN']}` | Kicks: `{stats['KICK']}` | Warns: `{stats['WARN']}` | Mutes: `{stats['MUTE']}`\n\n"
                    "**`💥` Ban Information:**\n"
                    f"[**Case #{self.case_id}**]({case_url}) & **Ban {ban_number}** | Banned for {duration_label}\n"
                    f"**Date:** <t:{case_created}:f>\n"
                    f"**Moderator:** <@{int(case['moderator_id'])}> (`{int(case['moderator_id'])}`)\n"
                    f"**Reason:** {reason}\n"
                    f"**Evidence:** {evidence}\n"
                    "**1. Why would you like to get unbanned?**\n"
                    f"{self.q1}\n\n"
                    "**2. Is there extra information you'd like to give?**\n"
                    f"{self.q2 or 'N/A'}\n\n"
                    "**Appeal Outcome:**\n"
                    f" {EMOJI_WAIT} Pending review"
                ),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            .set_author(
                name=f"@{interaction.user.name}'s Ban Appeal",
                icon_url=APPEAL_AUTHOR_ICON_URL,
            )
            .set_image(url=BANNER_IMAGE_URL)
            .set_footer(
                text="OVRP | Oceanview Roleplay Management",
                icon_url=APPEAL_STAFF_FOOTER_ICON_URL,
            )
        )

        view = AppealStaffView(appeal_id, self.user_id)

        try:
            msg = await appeals_channel.send(embed=staff_embed, view=staff_view)
            set_appeal_staff_message(appeal_id, msg.id)
        except discord.Forbidden:
            await send_error(
                interaction,
                500,
                "I do not have permission to send messages in the appeals channel.",
            )
            return
        except discord.HTTPException:
            await send_error(
                interaction,
                520,
                "Failed to post the appeal due to an unknown error.",
            )
            return

        await interaction.response.send_message(
            content="Your appeal has been submitted. Please check your DMs.",
            ephemeral=True,
        )

class BanAppealView(discord.ui.View):
    def __init__(self, case_id: int, user_id: int, duration_seconds: int, created_at: int):
        super().__init__(timeout=None)
        self.case_id = int(case_id)
        self.user_id = int(user_id)
        self.duration_seconds = int(duration_seconds)
        self.created_at = int(created_at)

    @discord.ui.button(label="Appeal", style=discord.ButtonStyle.primary)
    async def appeal_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.user.id != self.user_id:
            await send_error(
                interaction,
                403,
                "Only the affected user can submit an appeal for this case.",
            )
            return

        guild = interaction.client.get_guild(GUILD_ID)
        if guild is None:
            await send_error(
                interaction,
                500,
                "The appeal system is currently unavailable. Please try again later.",
            )
            return

        # Check Discord-side ban still active
        if not await is_currently_banned(guild, self.user_id):
            await send_error(
                interaction,
                409,
                "You are no longer banned from the server, so you cannot appeal this case.",
            )
            return

        # Only permanent or > 4 days bans are appealable (same rule as button visibility)
        if self.duration_seconds != 0 and self.duration_seconds <= 4 * 24 * 60 * 60:
            await send_error(
                interaction,
                400,
                "This ban is not eligible for appeal.",
            )
            return

        # Must wait 3 days after ban to appeal
        min_ts = self.created_at + (3 * 24 * 60 * 60)
        now_ts = int(time.time())
        if (not SIMULATION_MODE) and now_ts < min_ts:
            ts_rel = discord_timestamp(min_ts, "R")
            ts_abs = discord_timestamp(min_ts, "f")
            embed = (
                discord.Embed(
                    color=0xF1C40F,
                    title=f"{EMOJI_WAIT} Appeal not yet available",
                    description=(
                        "You cannot appeal this ban yet.\n\n"
                        f"You may submit an appeal {ts_rel}."
                    ),
                )
                .set_author(
                    name="OVRP | Appeal System",
                    icon_url=OVRP_LOGO_URL,
                )
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Ensure no existing pending appeal
        # Block if an appeal for this ban has already been accepted
        if has_accepted_appeal_for_case(guild.id, self.case_id, self.user_id):
            await send_error(
                interaction,
                409,
                "This ban appeal has already been accepted. You cannot submit another appeal for this case.",
            )
            return

        # Ensure no existing pending appeal
        existing = get_active_appeal_for_case(guild.id, self.case_id, self.user_id)
        if existing is not None:
            await send_error(
                interaction,
                409,
                "You already have a pending appeal for this ban.",
            )
            return


class AppealMoreInfoModal(discord.ui.Modal, title="Request More Information"):
    question = discord.ui.TextInput(
        label="Question for the user",
        style=discord.TextStyle.paragraph,
        max_length=900,
        required=True,
    )

    def __init__(self, appeal_id: int, user_id: int):
        super().__init__()
        self.appeal_id = int(appeal_id)
        self.user_id = int(user_id)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            await send_error(
                interaction,
                500,
                "Only administrators can request more information on appeals.",
            )
            return

        appeal = get_appeal(self.appeal_id)
        if appeal is None:
            await send_error(
                interaction,
                404,
                "This appeal no longer exists.",
            )
            return

        guild = interaction.client.get_guild(GUILD_ID)
        if guild is None:
            await send_error(
                interaction,
                500,
                "The appeal system is currently unavailable.",
            )
            return

        target_id = int(appeal["user_id"])
        if target_id != self.user_id:
            await send_error(
                interaction,
                409,
                "This appeal no longer matches the original user.",
            )
            return

        # DM the user asking for more info
        try:
            user = await interaction.client.fetch_user(target_id)
        except Exception:
            user = None

        appeal_code = f"A-{int(appeal['appeal_id']):03d}"
        created_at = int(time.time())
        ts_str = discord_timestamp(created_at, "f")

        dm_embed = (
            discord.Embed(
                color=15822351,
                title=f"🔎 More Information Required | ID: {appeal_code}",
                description=(
                    "Staff require **additional information** to continue reviewing your appeal.\n"
                    "Please submit the requested details using the form below.\n\n"
                    f"{EMOJI_WAIT} You must respond within **48 hours** of this notice.\n"
                ),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            .set_author(
                name="Appeal Management",
                icon_url=APPEAL_AUTHOR_ICON_URL,
            )
            .set_image(url=BANNER_IMAGE_URL)
            .set_footer(
                text="Failure to respond may result in your appeal being closed. ",
            )
        )

        view = AppealMoreInfoResponseView(self.appeal_id, self.user_id, str(self.question))

        if user is not None:
            try:
                await user.send(embed=dm_embed, view=view)
            except Exception:
                pass

        await interaction.response.send_message(
            content="The user has been asked for more information.",
            ephemeral=True,
        )


class AppealMoreInfoAnswerModal(discord.ui.Modal, title="Answer the Question"):
    answer = discord.ui.TextInput(
        label="Your answer",
        style=discord.TextStyle.paragraph,
        max_length=900,
        required=True,
    )

    def __init__(self, appeal_id: int, user_id: int, question: str):
        super().__init__()
        self.appeal_id = int(appeal_id)
        self.user_id = int(user_id)
        self.question_text = question

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await send_error(
                interaction,
                403,
                "Only the affected user can respond to this question.",
            )
            return

        appeal = get_appeal(self.appeal_id)
        if appeal is None:
            await send_error(
                interaction,
                404,
                "This appeal no longer exists.",
            )
            return

        guild = interaction.client.get_guild(GUILD_ID)
        if guild is None:
            await send_error(
                interaction,
                500,
                "The appeal system is currently unavailable.",
            )
            return

        appeals_channel = guild.get_channel(APPEALS_CHANNEL_ID)
        if not isinstance(
            appeals_channel,
            (discord.TextChannel, discord.Thread, discord.ForumChannel),
        ):
            await send_error(
                interaction,
                503,
                "Appeals channel is misconfigured. Please contact an administrator.",
            )
            return

        created_at = int(time.time())
        ts_str = discord_timestamp(created_at, "f")
        appeal_code = f"A-{int(appeal['appeal_id']):03d}"

        staff_embed = (
            discord.Embed(
                color=15105570,
                title=f"{EMOJI_OVRP1} Appeal update - Additional Information Received | ID: {appeal_code}",
                description=(
                    f"**Question:** (requested by <@{int(appeal['last_updated_by'])}>)\n"
                    f"{self.question_text}\n\n"
                    f"**Answer:** (submitted by <@{self.user_id}> | `{self.user_id}`)\n"
                    f"{self.answer}"
                ),
            )
            .set_author(
                name=f"{interaction.user.name}'s Ban Appeal:",
                icon_url=APPEAL_AUTHOR_ICON_URL,
            )
            .set_image(url=BANNER_IMAGE_URL)
        )

        try:
            await appeals_channel.send(embed=staff_embed)
        except Exception:
            pass

        await interaction.response.send_message(
            content="Your additional information has been submitted.",
            ephemeral=True,
        )


class AppealMoreInfoResponseView(discord.ui.View):
    def __init__(self, appeal_id: int, user_id: int, question: str):
        super().__init__(timeout=None)
        self.appeal_id = int(appeal_id)
        self.user_id = int(user_id)
        self.question_text = question

    @discord.ui.button(label="Respond", style=discord.ButtonStyle.primary)
    async def respond_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if interaction.user.id != self.user_id:
            await send_error(
                interaction,
                403,
                "Only the affected user can respond to this question.",
            )
            return

        modal = AppealMoreInfoAnswerModal(self.appeal_id, self.user_id, self.question_text)
        await interaction.response.send_modal(modal)

class AppealStaffView(discord.ui.View):
    def __init__(self, appeal_id: int, user_id: int):
        super().__init__(timeout=None)
        self.appeal_id = int(appeal_id)
        self.user_id = int(user_id)

    async def _get_appeal_and_check_admin(
        self,
        interaction: discord.Interaction,
    ) -> Optional[sqlite3.Row]:
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            await send_error(
                interaction,
                500,
                "Only administrators can process appeals.",
            )
            return None

        appeal = get_appeal(self.appeal_id)
        if appeal is None:
            await send_error(
                interaction,
                404,
                "This appeal no longer exists.",
            )
            return None

        if str(appeal["status"]).upper() != "PENDING":
            await send_error(
                interaction,
                409,
                "This appeal has already been processed.",
            )
            return None

        return appeal

    def _disable_buttons(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    async def _update_staff_message_color(
        self,
        interaction: discord.Interaction,
        color: int,
        outcome_text: str,
    ) -> None:
        try:
            if not interaction.message or not interaction.message.embeds:
                return
            base = interaction.message.embeds[0]
            base.color = discord.Color(color)
            # Add / replace an Outcome field
            fields = [f for f in base.fields]
            # Remove existing Outcome
            base.clear_fields()
            for f in fields:
                if f.name != "Outcome":
                    base.add_field(name=f.name, value=f.value, inline=f.inline)
            base.add_field(name="Outcome", value=outcome_text, inline=False)
            await interaction.message.edit(embed=base, view=self)
        except Exception:
            pass

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        appeal = await self._get_appeal_and_check_admin(interaction)
        if appeal is None:
            return

        guild = interaction.guild or interaction.client.get_guild(GUILD_ID)
        if guild is None:
            await send_error(
                interaction,
                500,
                "The appeal system is currently unavailable.",
            )
            return

        user_id = int(appeal["user_id"])
        case_id = int(appeal["case_id"])
        appeal_id = int(appeal["appeal_id"])
        appeal_code = f"A-{appeal_id:03d}"

        update_appeal_status(appeal_id, "ACCEPTED", interaction.user.id, "Appeal accepted")

        # Try to unban user
        target_user = None
        try:
            target_user = await interaction.client.fetch_user(user_id)
        except Exception:
            pass

        if not SIMULATION_MODE and guild is not None:
            try:
                await guild.unban(discord.Object(id=user_id))
            except discord.NotFound:
                pass
            except discord.Forbidden:
                # Show, but don't fail the entire callback
                logger.warning("Failed to unban user %s while accepting appeal.", user_id)
            except discord.HTTPException:
                logger.warning("HTTP error while unbanning user %s on appeal accept.", user_id)

        # Log UNBAN case
        reason = "Ban appeal accepted"
        evidence_text = "Appeal accepted by staff"

        auto_case_id, unban_number = create_case(
            guild.id,
            user_id,
            interaction.user.id,
            "UNBAN",
            reason,
            evidence_text,
            None,
            None,
            automatic=False,
        )

        created_at = int(time.time())
        ts_str = discord_timestamp(created_at, "f")
        author_name = str(interaction.user)
        author_icon = interaction.user.display_avatar.url

        staff_embed = (
            discord.Embed(
                color=0x2ECC71,
                title=f"{EMOJI_OVRP1} Appeal Accepted | Unban Case #{auto_case_id}",
                timestamp=datetime.datetime.utcfromtimestamp(created_at),
            )
            .set_author(
                name=author_name,
                icon_url=author_icon,
            )
            .set_footer(text="OVRP | Moderation Systems")
        )
        staff_embed.add_field(
            name="Member",
            value=f"<@{user_id}> (`{user_id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Moderator",
            value=f"<@{interaction.user.id}> (`{interaction.user.id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        staff_embed.add_field(
            name="Evidence",
            value=evidence_text,
            inline=True,
        )
        staff_embed.add_field(
            name="Date",
            value=ts_str,
            inline=True,
        )

        staff_channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
        log_url = ""
        if isinstance(
            staff_channel,
            (discord.TextChannel, discord.Thread, discord.ForumChannel),
        ):
            try:
                msg = await staff_channel.send(embed=staff_embed)
                set_case_staff_message(auto_case_id, msg.id)
                log_url = (
                    f"https://discord.com/channels/{guild.id}/"
                    f"{STAFF_LOG_CHANNEL_ID}/{msg.id}"
                )
            except Exception:
                pass

        # DM user
        if target_user is not None:
            dm_embed = (
                discord.Embed(
                    color=4772190,
                    title=f"{EMOJI_CHECK} Appeal accepted | ID: {appeal_code}",
                    description=(
                        "Your ban appeal for **OVRP | Oceanview Roleplay** has been **accepted**.\n\n"
                        "**You may rejoin the server using the link below:**\n"
                        "https://discord.gg/ovrp"
                    ),
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                )
                .set_author(
                    name="Appeal Response",
                    icon_url=APPEAL_AUTHOR_ICON_URL,
                )
                .set_image(url=BANNER_IMAGE_URL)
                .set_footer(
                    text="This appeal has been reviewed and approved by the OVRP Management Team.",
                )
            )

            try:
                await target_user.send(embed=dm_embed)
            except Exception:
                pass

        # Update appeal message
        self._disable_buttons()
        await self._update_staff_message_color(
            interaction,
            0x2ECC71,
            "Appeal **ACCEPTED** – user unbanned.",
        )

        await interaction.response.send_message(
            content="Appeal accepted and user unbanned.",
            ephemeral=True,
        )

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        appeal = await self._get_appeal_and_check_admin(interaction)
        if appeal is None:
            return

        update_appeal_status(
            int(appeal["appeal_id"]),
            "DENIED",
            interaction.user.id,
            "Appeal denied",
        )

        self._disable_buttons()
        await self._update_staff_message_color(
            interaction,
            0xE74C3C,
            "Appeal **DENIED** – ban remains in place.",
        )

        # DM user
        user_id = int(appeal["user_id"])
        appeal_code = f"A-{int(appeal['appeal_id']):03d}"
        try:
            user = await interaction.client.fetch_user(user_id)
        except Exception:
            user = None

        if user is not None:
            dm_embed = (
                discord.Embed(
                    color=0xE74C3C,
                    title=f"{EMOJI_OVRP1} Appeal denied | ID: {appeal_code}",
                    description=(
                        "Your ban appeal for **OVRP | Oceanview Roleplay** has been **denied**.\n\n"
                        "Your ban will remain in place. You may be able to appeal again in the future "
                        "if new information becomes available."
                    ),
                )
                .set_author(
                    name="OVRP | Appeal System",
                    icon_url=OVRP_LOGO_URL,
                )
                .set_image(url=BANNER_IMAGE_URL)
            )
            try:
                await user.send(embed=dm_embed)
            except Exception:
                pass

        await interaction.response.send_message(
            content="Appeal denied.",
            ephemeral=True,
        )

    @discord.ui.button(label="More Info", style=discord.ButtonStyle.secondary)
    async def more_info_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        appeal = await self._get_appeal_and_check_admin(interaction)
        if appeal is None:
            return

        modal = AppealMoreInfoModal(self.appeal_id, self.user_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="View History", style=discord.ButtonStyle.secondary)
    async def view_history_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await send_error(
                interaction,
                500,
                "Only staff members can view modlogs.",
            )
            return

        guild = interaction.guild or interaction.client.get_guild(GUILD_ID)
        if guild is None:
            await send_error(
                interaction,
                500,
                "This can only be used inside the server.",
            )
            return

        rows = fetch_cases_for_user(guild.id, self.user_id)
        if not rows:
            await send_error(
                interaction,
                404,
                "This user has no moderation history.",
            )
            return

        user = interaction.client.get_user(self.user_id) or discord.Object(id=self.user_id)
        view = ModlogsView(guild.id, user, rows, owner_id=interaction.user.id)  # type: ignore
        embed = view.create_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)



# ============================================================
# MODERATION COG
# ============================================================


class Moderation(commands.Cog):
    def __init__(self, bot_: commands.Bot):
        self.bot = bot_

    # ------------------------------
    # /ban
    # ------------------------------

    @app_commands.command(
        name="ban",
        description="Ban a member from the server.",
    )
    @app_commands.describe(
        member="The member to ban.",
        reason="Reason for the ban.",
        duration_days="Ban duration in days (0 for permanent).",
        evidence_url="Link to evidence (image, message link, etc.).",
        evidence_attachment="Upload evidence from your PC.",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def ban_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        duration_days: app_commands.Range[int, 0, 365],
        evidence_url: Optional[str] = None,
        evidence_attachment: Optional[discord.Attachment] = None,
    ):
        guild = interaction.guild
        if guild is None:
            await send_error(interaction, 500, "This command can only be used inside the server.")
            return

        if not isinstance(interaction.user, discord.Member):
            await send_error(interaction, 401, "You must be a server member to run this command.")
            return

        if not is_staff(interaction.user):
            await send_error(
                interaction,
                500,
                "You must be a staff member to use moderation commands.",
            )
            return

        # Moderators must use /reqban (non-ephemeral error)
        if is_moderator(interaction.user) and not is_admin(interaction.user):
            await send_error(
                interaction,
                500,
                "Moderators cannot use /ban directly. Please use `/reqban` to request a ban.",
                ephemeral=False,
            )
            return

        if SIMULATION_MODE and not is_admin(interaction.user):
            await send_error(
                interaction,
                500,
                "This command is currently running in simulation mode. "
                "Only server administrators can use simulated moderation commands.",
            )
            return

        if evidence_url is None and evidence_attachment is None:
            await send_error(
                interaction,
                400,
                "You must provide evidence via URL or attachment.",
            )
            return

        if not SIMULATION_MODE:
            if member == interaction.user:
                await send_error(interaction, 400, "You cannot ban yourself.")
                return

            if member == guild.owner:
                await send_error(interaction, 500, "You cannot ban the server owner.")
                return

            if (
                member.top_role >= interaction.user.top_role
                and not interaction.user.guild_permissions.administrator
            ):
                await send_error(
                    interaction,
                    500,
                    "You cannot ban a member with an equal or higher role than yours.",
                )
                return

            if member.top_role >= guild.me.top_role:  # type: ignore
                await send_error(
                    interaction,
                    500,
                    "I cannot ban this member because their top role is higher or equal to mine.",
                )
                return

        # Prevent double bans while an active ban case exists
        if has_active_ban(guild.id, member.id):
            await send_error(
                interaction,
                409,
                "This user already has an active ban case. Please review their modlogs before applying another ban.",
            )
            return


        evidence_text = join_evidence(evidence_url, evidence_attachment)

        duration_secs = duration_days_to_seconds(duration_days) if duration_days > 0 else 0
        expires_at = int(time.time()) + duration_secs if duration_secs > 0 else None

        case_id, ban_number = create_case(
            guild.id,
            member.id,
            interaction.user.id,
            "BAN",
            reason,
            evidence_text,
            duration_secs if duration_secs > 0 else None,
            expires_at,
            automatic=False,
        )

        created_at = int(time.time())
        ts_str = discord_timestamp(created_at, "f")
        duration_label = f"{duration_days} day(s)" if duration_days > 0 else "Permanent"

        staff_embed = (
            discord.Embed(
                color=0xE74C3C,
                title=f"{EMOJI_OVRP1} Ban | Case #{case_id} & Ban {ban_number}",
                timestamp=datetime.datetime.utcfromtimestamp(created_at),
            )
            .set_author(
                name=str(interaction.user),
                icon_url=interaction.user.display_avatar.url,
            )
            .set_footer(text="OVRP | Moderation Systems")
        )
        staff_embed.add_field(
            name="Member",
            value=f"<@{member.id}> (`{member.id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Moderator",
            value=f"<@{interaction.user.id}> (`{interaction.user.id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        staff_embed.add_field(
            name="Evidence",
            value=evidence_text,
            inline=True,
        )
        staff_embed.add_field(
            name="Duration",
            value=duration_label,
            inline=True,
        )
        staff_embed.add_field(
            name="Date",
            value=ts_str,
            inline=True,
        )

        staff_channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
        if not isinstance(
            staff_channel,
            (discord.TextChannel, discord.Thread, discord.ForumChannel),
        ):
            await send_error(
                interaction,
                503,
                "Staff log channel is misconfigured. Please contact an administrator.",
            )
            return

        try:
            msg = await staff_channel.send(embed=staff_embed)
        except discord.Forbidden:
            await send_error(
                interaction,
                500,
                "I do not have permission to send messages in the staff log channel.",
            )
            return
        except discord.HTTPException:
            await send_error(
                interaction,
                520,
                "Failed to post to the staff log channel due to an unknown error.",
            )
            return

        set_case_staff_message(case_id, msg.id)
        log_url = f"https://discord.com/channels/{guild.id}/{STAFF_LOG_CHANNEL_ID}/{msg.id}"

        dm_embed = (
            discord.Embed(
                color=0xE74C3C,
                title=f"{EMOJI_OVRP1} Moderation Action Issued",
                description=(
                    f"You have been banned from **OVRP | Oceanview Roleplay** | **Ban {ban_number}**\n"
                ),
            )
            .set_author(
                name="OVRP | Moderation Notice",
                icon_url=OVRP_LOGO_URL,
            )
            .set_image(url=BANNER_IMAGE_URL)
            .set_footer(
                text=f"Case #{case_id} | You may submit an appeal if you believe this decision was incorrect",
            )
        )
        dm_embed.add_field(
            name="Duration",
            value=duration_label,
            inline=True,
        )
        dm_embed.add_field(
            name="Evidence",
            value=evidence_text,
            inline=True,
        )
        dm_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )

        view: Optional[discord.ui.View] = None
        if duration_days == 0 or duration_days > 4:
            view = discord.ui.View(timeout=None)
            button_appeal = discord.ui.Button(
                label="Appeal",
                style=discord.ButtonStyle.primary,
            )

            async def appeal_button_callback(button_interaction: discord.Interaction):
                await send_error(
                    button_interaction,
                    501,
                    "The appeal system is not configured yet.",
                )

            button_appeal.callback = appeal_button_callback  # type: ignore
            view.add_item(button_appeal)

        try:
            if view:
                await member.send(embed=dm_embed, view=view)
            else:
                await member.send(embed=dm_embed)
        except Exception:
            pass

        if not SIMULATION_MODE:
            try:
                await guild.ban(
                    member,
                    reason=f"[Case #{case_id}] {reason}",
                    delete_message_days=0,
                )
            except discord.Forbidden:
                await send_error(
                    interaction,
                    500,
                    "I do not have permission to ban this member.",
                )
                return
            except discord.HTTPException:
                await send_error(
                    interaction,
                    520,
                    "Failed to ban this member due to an unknown error.",
                )
                return

        confirm_embed = build_confirm_embed(
            action_label="Ban",
            case_id=case_id,
            action_number=ban_number,
            member=member,
            log_url=log_url,
            duration_text=duration_label,
        )
        await interaction.response.send_message(
            embed=confirm_embed,
            ephemeral=False,
        )

    # ------------------------------
    # /reqban
    # ------------------------------

    @app_commands.command(
        name="reqban",
        description="Request a ban to be approved by an administrator.",
    )
    @app_commands.describe(
        member="The member you want to request a ban for.",
        reason="Reason for the ban.",
        duration_days="Requested ban duration in days (0 for permanent).",
        evidence_url="Link to evidence (image, message link, etc.).",
        evidence_attachment="Upload evidence from your PC.",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def reqban_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        duration_days: app_commands.Range[int, 0, 365],
        evidence_url: Optional[str] = None,
        evidence_attachment: Optional[discord.Attachment] = None,
    ):
        guild = interaction.guild
        if guild is None:
            await send_error(
                interaction,
                500,
                "This command can only be used inside the server.",
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await send_error(
                interaction,
                401,
                "You must be a server member to run this command.",
            )
            return

        if not (is_moderator(interaction.user) or is_admin(interaction.user)):
            await send_error(
                interaction,
                500,
                "You must be a moderator or administrator to use /reqban.",
            )
            return

        if evidence_url is None and evidence_attachment is None:
            await send_error(
                interaction,
                400,
                "You must provide evidence via URL or attachment.",
            )
            return

        # Prevent double bans while an active ban case exists
        if has_active_ban(guild.id, member.id):
            await send_error(
                interaction,
                409,
                "This user already has an active ban case. Please review their modlogs before applying another ban.",
            )
            return


        evidence_text = join_evidence(evidence_url, evidence_attachment)
        duration_secs = duration_days_to_seconds(duration_days) if duration_days > 0 else 0

        req_id = create_ban_request(
            guild.id,
            member.id,
            interaction.user.id,
            duration_secs if duration_secs > 0 else None,
            reason,
            evidence_text,
        )

        created_at = int(time.time())
        ts_str = discord_timestamp(created_at, "f")
        duration_label = (
            f"{duration_days} day(s)" if duration_days > 0 else "Permanent"
        )
        title_id = f"req-{req_id:03d}"

        request_embed = (
            discord.Embed(
                color=0x3498DB,
                title=f"{EMOJI_OVRP1} Ban Request | ID: {title_id}",
                timestamp=datetime.datetime.utcfromtimestamp(created_at),
                description=(
                    "A ban has been requested and is awaiting administrator review.\n\n"
                    f"**Requested By:** <@{interaction.user.id}> (`{interaction.user.id}`)\n"
                    f"**Target:** <@{member.id}> (`{member.id}`)"
                ),
            )
            .set_author(
                name=str(interaction.user),
                icon_url=interaction.user.display_avatar.url,
            )
            .set_footer(text="OVRP | Moderation Systems • Use the buttons below to approve or deny.")
        )
        request_embed.add_field(
            name="Duration",
            value=duration_label,
            inline=True,
        )
        request_embed.add_field(
            name="Evidence",
            value=evidence_text,
            inline=True,
        )
        request_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        request_embed.add_field(
            name="Requested At",
            value=ts_str,
            inline=True,
        )

        channel = guild.get_channel(BAN_REQUEST_CHANNEL_ID)
        if not isinstance(
            channel,
            (discord.TextChannel, discord.Thread, discord.ForumChannel),
        ):
            await send_error(
                interaction,
                503,
                "Ban request channel is misconfigured. Please contact an administrator.",
            )
            return

        view = ReqBanView(req_id)

        try:
            msg = await channel.send(embed=request_embed, view=view)
        except discord.Forbidden:
            await send_error(
                interaction,
                500,
                "I do not have permission to send messages in the ban request channel.",
            )
            return
        except discord.HTTPException:
            await send_error(
                interaction,
                520,
                "Failed to post the ban request due to an unknown error.",
            )
            return

        set_ban_request_message(req_id, msg.id)

        log_url = f"https://discord.com/channels/{guild.id}/{BAN_REQUEST_CHANNEL_ID}/{msg.id}"

        confirm_embed = (
            discord.Embed(
                color=0x2ECC71,
                title=f"{EMOJI_OVRP1} Ban request created | ID: {title_id}",
                url=log_url,
                description=(
                    f"Your ban request for <@{member.id}> has been logged as `{title_id}` "
                    "and is awaiting administrator review."
                ),
            )
            .set_author(
                name="OVRP | Moderation System",
                icon_url=OVRP_LOGO_URL,
            )
        )

        await interaction.response.send_message(embed=confirm_embed, ephemeral=True)

    # ------------------------------
    # /kick
    # ------------------------------

    @app_commands.command(
        name="kick",
        description="Kick a member from the server.",
    )
    @app_commands.describe(
        member="The member to kick.",
        reason="Reason for the kick.",
        evidence_url="Link to evidence (image, message link, etc.).",
        evidence_attachment="Upload evidence from your PC.",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def kick_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        evidence_url: Optional[str] = None,
        evidence_attachment: Optional[discord.Attachment] = None,
    ):
        guild = interaction.guild
        if guild is None:
            await send_error(interaction, 500, "This command can only be used inside the server.")
            return

        if not isinstance(interaction.user, discord.Member):
            await send_error(interaction, 401, "You must be a server member to run this command.")
            return

        if not is_staff(interaction.user):
            await send_error(
                interaction,
                500,
                "You must be a staff member to use moderation commands.",
            )
            return

        if SIMULATION_MODE and not is_admin(interaction.user):
            await send_error(
                interaction,
                500,
                "This command is currently running in simulation mode. "
                "Only server administrators can use simulated moderation commands.",
            )
            return

        if evidence_url is None and evidence_attachment is None:
            await send_error(
                interaction,
                400,
                "You must provide evidence via URL or attachment.",
            )
            return

        if not SIMULATION_MODE:
            if member == interaction.user:
                await send_error(interaction, 400, "You cannot kick yourself.")
                return

            if member == guild.owner:
                await send_error(interaction, 500, "You cannot kick the server owner.")
                return

            if (
                member.top_role >= interaction.user.top_role
                and not interaction.user.guild_permissions.administrator
            ):
                await send_error(
                    interaction,
                    500,
                    "You cannot kick a member with an equal or higher role than yours.",
                )
                return

            if member.top_role >= guild.me.top_role:  # type: ignore
                await send_error(
                    interaction,
                    500,
                    "I cannot kick this member because their top role is higher or equal to mine.",
                )
                return

        evidence_text = join_evidence(evidence_url, evidence_attachment)

        case_id, kick_number = create_case(
            guild.id,
            member.id,
            interaction.user.id,
            "KICK",
            reason,
            evidence_text,
            None,
            None,
            automatic=False,
        )

        created_at = int(time.time())
        ts_str = discord_timestamp(created_at, "f")

        staff_embed = (
            discord.Embed(
                color=0xE67E22,
                title=f"{EMOJI_OVRP1} Kick | Case #{case_id} & Kick {kick_number}",
                timestamp=datetime.datetime.utcfromtimestamp(created_at),
            )
            .set_author(
                name=str(interaction.user),
                icon_url=interaction.user.display_avatar.url,
            )
            .set_footer(text="OVRP | Moderation Systems")
        )
        staff_embed.add_field(
            name="Member",
            value=f"<@{member.id}> (`{member.id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Moderator",
            value=f"<@{interaction.user.id}> (`{interaction.user.id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        staff_embed.add_field(
            name="Evidence",
            value=evidence_text,
            inline=True,
        )
        staff_embed.add_field(
            name="Date",
            value=ts_str,
            inline=True,
        )

        staff_channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
        if not isinstance(
            staff_channel,
            (discord.TextChannel, discord.Thread, discord.ForumChannel),
        ):
            await send_error(
                interaction,
                503,
                "Staff log channel is misconfigured. Please contact an administrator.",
            )
            return

        try:
            msg = await staff_channel.send(embed=staff_embed)
        except discord.Forbidden:
            await send_error(
                interaction,
                500,
                "I do not have permission to send messages in the staff log channel.",
            )
            return
        except discord.HTTPException:
            await send_error(
                interaction,
                520,
                "Failed to post to the staff log channel due to an unknown error.",
            )
            return

        set_case_staff_message(case_id, msg.id)
        log_url = f"https://discord.com/channels/{guild.id}/{STAFF_LOG_CHANNEL_ID}/{msg.id}"

        dm_embed = (
            discord.Embed(
                color=0xE67E22,
                title=f"{EMOJI_OVRP1} Moderation Action Issued",
        description=(
                    f"You have been kicked from **OVRP | Oceanview Roleplay** | **Kick {kick_number}**\n"
                ),
            )
            .set_author(
                name="OVRP | Moderation Notice",
                icon_url=OVRP_LOGO_URL,
            )
            .set_image(url=BANNER_IMAGE_URL)
            .set_footer(
                text=f"Case #{case_id} | You may contact staff if you have questions about this action.",
            )
        )
        dm_embed.add_field(
            name="Evidence",
            value=evidence_text,
            inline=True,
        )
        dm_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        try:
            await member.send(embed=dm_embed)
        except Exception:
            pass

        if not SIMULATION_MODE:
            try:
                await guild.kick(member, reason=f"[Case #{case_id}] {reason}")
            except discord.Forbidden:
                await send_error(
                    interaction,
                    500,
                    "I do not have permission to kick this member.",
                )
                return
            except discord.HTTPException:
                await send_error(
                    interaction,
                    520,
                    "Failed to kick this member due to an unknown error.",
                )
                return

        confirm_embed = build_confirm_embed(
            action_label="Kick",
            case_id=case_id,
            action_number=kick_number,
            member=member,
            log_url=log_url,
        )
        await interaction.response.send_message(
            embed=confirm_embed,
            ephemeral=False,
        )

    # ------------------------------
    # /warn
    # ------------------------------

    @app_commands.command(
        name="warn",
        description="Warn a member.",
    )
    @app_commands.describe(
        member="The member to warn.",
        reason="Reason for the warning.",
        evidence_url="Link to evidence (image, message link, etc.).",
        evidence_attachment="Upload evidence from your PC.",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def warn_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        evidence_url: Optional[str] = None,
        evidence_attachment: Optional[discord.Attachment] = None,
    ):
        guild = interaction.guild
        if guild is None:
            await send_error(interaction, 500, "This command can only be used inside the server.")
            return

        if not isinstance(interaction.user, discord.Member):
            await send_error(interaction, 401, "You must be a server member to run this command.")
            return

        if not is_staff(interaction.user):
            await send_error(
                interaction,
                500,
                "You must be a staff member to use moderation commands.",
            )
            return

        if SIMULATION_MODE and not is_admin(interaction.user):
            await send_error(
                interaction,
                500,
                "This command is currently running in simulation mode. "
                "Only server administrators can use simulated moderation commands.",
            )
            return

        if evidence_url is None and evidence_attachment is None:
            await send_error(
                interaction,
                400,
                "You must provide evidence via URL or attachment.",
            )
            return

        if not SIMULATION_MODE and member == interaction.user:
            await send_error(interaction, 400, "You cannot warn yourself.")
            return

        evidence_text = join_evidence(evidence_url, evidence_attachment)

        case_id, warn_number = create_case(
            guild.id,
            member.id,
            interaction.user.id,
            "WARN",
            reason,
            evidence_text,
            None,
            None,
            automatic=False,
        )

        created_at = int(time.time())
        ts_str = discord_timestamp(created_at, "f")

        staff_embed = (
            discord.Embed(
                color=0xE67E22,
                title=f"{EMOJI_OVRP1} Warn | Case #{case_id} & Warn {warn_number}",
                timestamp=datetime.datetime.utcfromtimestamp(created_at),
            )
            .set_author(
                name=str(interaction.user),
                icon_url=interaction.user.display_avatar.url,
            )
            .set_footer(text="OVRP | Moderation Systems")
        )
        staff_embed.add_field(
            name="Member",
            value=f"<@{member.id}> (`{member.id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Moderator",
            value=f"<@{interaction.user.id}> (`{interaction.user.id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        staff_embed.add_field(
            name="Evidence",
            value=evidence_text,
            inline=True,
        )
        staff_embed.add_field(
            name="Date",
            value=ts_str,
            inline=True,
        )

        staff_channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
        if not isinstance(
            staff_channel,
            (discord.TextChannel, discord.Thread, discord.ForumChannel),
        ):
            await send_error(
                interaction,
                503,
                "Staff log channel is misconfigured. Please contact an administrator.",
            )
            return

        try:
            msg = await staff_channel.send(embed=staff_embed)
        except discord.Forbidden:
            await send_error(
                interaction,
                500,
                "I do not have permission to send messages in the staff log channel.",
            )
            return
        except discord.HTTPException:
            await send_error(
                interaction,
                520,
                "Failed to post to the staff log channel due to an unknown error.",
            )
            return

        set_case_staff_message(case_id, msg.id)
        log_url = f"https://discord.com/channels/{guild.id}/{STAFF_LOG_CHANNEL_ID}/{msg.id}"

        dm_embed = (
            discord.Embed(
                color=0xE67E22,
                title=f"{EMOJI_OVRP1} Moderation Action Issued",
                description=(
                    f"You have received a warning in **OVRP | Oceanview Roleplay** | **Warning {warn_number}**\n"
                ),
            )
            .set_author(
                name="OVRP | Moderation Notice",
                icon_url=OVRP_LOGO_URL,
            )
            .set_image(url=BANNER_IMAGE_URL)
            .set_footer(
                text=f"Case #{case_id} | Please follow the community rules to avoid further action.",
            )
        )
        dm_embed.add_field(
            name="Evidence",
            value=evidence_text,
            inline=True,
        )
        dm_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        try:
            await member.send(embed=dm_embed)
        except Exception:
            pass

        confirm_embed = build_confirm_embed(
            action_label="Warn",
            case_id=case_id,
            action_number=warn_number,
            member=member,
            log_url=log_url,
        )
        await interaction.response.send_message(
            embed=confirm_embed,
            ephemeral=False,
        )

    # ------------------------------
    # /mute
    # ------------------------------

    @app_commands.command(
        name="mute",
        description="Mute a member (duration in hours).",
    )
    @app_commands.describe(
        member="The member to mute.",
        reason="Reason for the mute.",
        duration_hours="Mute duration in hours.",
        evidence_url="Link to evidence (image, message link, etc.).",
        evidence_attachment="Upload evidence from your PC.",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def mute_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        duration_hours: app_commands.Range[int, 1, 672],
        evidence_url: Optional[str] = None,
        evidence_attachment: Optional[discord.Attachment] = None,
    ):
        guild = interaction.guild
        if guild is None:
            await send_error(interaction, 500, "This command can only be used inside the server.")
            return

        if not isinstance(interaction.user, discord.Member):
            await send_error(interaction, 401, "You must be a server member to run this command.")
            return

        if not is_staff(interaction.user):
            await send_error(
                interaction,
                500,
                "You must be a staff member to use moderation commands.",
            )
            return

        if SIMULATION_MODE and not is_admin(interaction.user):
            await send_error(
                interaction,
                500,
                "This command is currently running in simulation mode. "
                "Only server administrators can use simulated moderation commands.",
            )
            return

        if evidence_url is None and evidence_attachment is None:
            await send_error(
                interaction,
                400,
                "You must provide evidence via URL or attachment.",
            )
            return

        if not SIMULATION_MODE and member == interaction.user:
            await send_error(interaction, 400, "You cannot mute yourself.")
            return

        # Prevent multiple active mutes on the same user
        if has_active_mute(guild.id, member.id):
            await send_error(
                interaction,
                409,
                "This user already has an active mute. Please unmute them before applying another mute.",
            )
            return

        if is_currently_timed_out(member):
            await send_error(
                interaction,
                409,
                "This member is already muted (timed out) in Discord.",
            )
            return


        evidence_text = join_evidence(evidence_url, evidence_attachment)
        duration_secs = duration_hours_to_seconds(duration_hours)
        expires_at = int(time.time()) + duration_secs

        case_id, mute_number = create_case(
            guild.id,
            member.id,
            interaction.user.id,
            "MUTE",
            reason,
            evidence_text,
            duration_secs,
            expires_at,
            automatic=False,
        )

        created_at = int(time.time())
        ts_str = discord_timestamp(created_at, "f")
        duration_label = f"{duration_hours} hour(s)"

        staff_embed = (
            discord.Embed(
                color=0xE67E22,
                title=f"{EMOJI_OVRP1} Mute | Case #{case_id} & Mute {mute_number}",
                timestamp=datetime.datetime.utcfromtimestamp(created_at),
            )
            .set_author(
                name=str(interaction.user),
                icon_url=interaction.user.display_avatar.url,
            )
            .set_footer(text="OVRP | Moderation Systems")
        )
        staff_embed.add_field(
            name="Member",
            value=f"<@{member.id}> (`{member.id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Moderator",
            value=f"<@{interaction.user.id}> (`{interaction.user.id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        staff_embed.add_field(
            name="Evidence",
            value=evidence_text,
            inline=True,
        )
        staff_embed.add_field(
            name="Duration",
            value=duration_label,
            inline=True,
        )
        staff_embed.add_field(
            name="Date",
            value=ts_str,
            inline=True,
        )

        staff_channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
        if not isinstance(
            staff_channel,
            (discord.TextChannel, discord.Thread, discord.ForumChannel),
        ):
            await send_error(
                interaction,
                503,
                "Staff log channel is misconfigured. Please contact an administrator.",
            )
            return

        try:
            msg = await staff_channel.send(embed=staff_embed)
        except discord.Forbidden:
            await send_error(
                interaction,
                500,
                "I do not have permission to send messages in the staff log channel.",
            )
            return
        except discord.HTTPException:
            await send_error(
                interaction,
                520,
                "Failed to post to the staff log channel due to an unknown error.",
            )
            return

        set_case_staff_message(case_id, msg.id)
        log_url = f"https://discord.com/channels/{guild.id}/{STAFF_LOG_CHANNEL_ID}/{msg.id}"

        dm_embed = (
            discord.Embed(
                color=0xE67E22,
                title=f"{EMOJI_OVRP1} Moderation Action Issued",
                description=(
                    f"You have been muted in **OVRP | Oceanview Roleplay** | **Mute {mute_number}**\n"
                ),
            )
            .set_author(
                name="OVRP | Moderation Notice",
                icon_url=OVRP_LOGO_URL,
            )
            .set_image(url=BANNER_IMAGE_URL)
            .set_footer(
                text=f"Case #{case_id} | You may contact staff if you have questions about this action.",
            )
        )
        dm_embed.add_field(
            name="Duration",
            value=duration_label,
            inline=True,
        )
        dm_embed.add_field(
            name="Evidence",
            value=evidence_text,
            inline=True,
        )
        dm_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        try:
            await member.send(embed=dm_embed)
        except Exception:
            pass

        if not SIMULATION_MODE:
            try:
                await member.edit(
                    timeout=datetime.timedelta(seconds=duration_secs),
                    reason=f"[Case #{case_id}] {reason}",
                )
            except discord.Forbidden:
                await send_error(
                    interaction,
                    500,
                    "I do not have permission to mute (timeout) this member.",
                )
                return
            except discord.HTTPException:
                await send_error(
                    interaction,
                    520,
                    "Failed to mute this member due to an unknown error.",
                )
                return

        confirm_embed = build_confirm_embed(
            action_label="Mute",
            case_id=case_id,
            action_number=mute_number,
            member=member,
            log_url=log_url,
            duration_text=duration_label,
        )
        await interaction.response.send_message(
            embed=confirm_embed,
            ephemeral=False,
        )

    # ------------------------------
    # /unmute
    # ------------------------------

    @app_commands.command(
        name="unmute",
        description="Unmute a member.",
    )
    @app_commands.describe(
        member="The member to unmute.",
        reason="Reason for the unmute.",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def unmute_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
    ):
        guild = interaction.guild
        if guild is None:
            await send_error(interaction, 500, "This command can only be used inside the server.")
            return

        if not isinstance(interaction.user, discord.Member):
            await send_error(interaction, 401, "You must be a server member to run this command.")
            return

        if not is_staff(interaction.user):
            await send_error(
                interaction,
                500,
                "You must be a staff member to use moderation commands.",
            )
            return

        if SIMULATION_MODE and not is_admin(interaction.user):
            await send_error(
                interaction,
                500,
                "This command is currently running in simulation mode. "
                "Only server administrators can use simulated moderation commands.",
            )
            return

        if not SIMULATION_MODE and member == interaction.user:
            await send_error(interaction, 400, "You cannot unmute yourself.")
            return

        evidence_text = "N/A"

        case_id, unmute_number = create_case(
            guild.id,
            member.id,
            interaction.user.id,
            "UNMUTE",
            reason,
            evidence_text,
            None,
            None,
            automatic=False,
        )

        created_at = int(time.time())
        ts_str = discord_timestamp(created_at, "f")

        staff_embed = (
            discord.Embed(
                color=0x2ECC71,
                title=f"{EMOJI_OVRP1} Unmute | Case #{case_id} & Unmute {unmute_number}",
                timestamp=datetime.datetime.utcfromtimestamp(created_at),
            )
            .set_author(
                name=str(interaction.user),
                icon_url=interaction.user.display_avatar.url,
            )
            .set_footer(text="OVRP | Moderation Systems")
        )
        staff_embed.add_field(
            name="Member",
            value=f"<@{member.id}> (`{member.id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Moderator",
            value=f"<@{interaction.user.id}> (`{interaction.user.id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        staff_embed.add_field(
            name="Evidence",
            value=evidence_text,
            inline=True,
        )
        staff_embed.add_field(
            name="Date",
            value=ts_str,
            inline=True,
        )

        staff_channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
        if not isinstance(
            staff_channel,
            (discord.TextChannel, discord.Thread, discord.ForumChannel),
        ):
            await send_error(
                interaction,
                503,
                "Staff log channel is misconfigured. Please contact an administrator.",
            )
            return

        try:
            msg = await staff_channel.send(embed=staff_embed)
        except discord.Forbidden:
            await send_error(
                interaction,
                500,
                "I do not have permission to send messages in the staff log channel.",
            )
            return
        except discord.HTTPException:
            await send_error(
                interaction,
                520,
                "Failed to post to the staff log channel due to an unknown error.",
            )
            return

        set_case_staff_message(case_id, msg.id)
        log_url = f"https://discord.com/channels/{guild.id}/{STAFF_LOG_CHANNEL_ID}/{msg.id}"

        dm_embed = (
            discord.Embed(
                color=0x2ECC71,
                title=f"{EMOJI_OVRP1} Moderation Action Issued",
                description="You have been unmuted in **OVRP | Oceanview Roleplay**\n",
            )
            .set_author(
                name="OVRP | Moderation Notice",
                icon_url=OVRP_LOGO_URL,
            )
            .set_image(url=BANNER_IMAGE_URL)
            .set_footer(
                text=f"Case #{case_id} | Thank you for your patience.",
            )
        )
        dm_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        try:
            await member.send(embed=dm_embed)
        except Exception:
            pass

        if not SIMULATION_MODE:
            try:
                await member.edit(timeout=None, reason=f"[Case #{case_id}] {reason}")
            except discord.Forbidden:
                await send_error(
                    interaction,
                    500,
                    "I do not have permission to clear timeout for this member.",
                )
                return
            except discord.HTTPException:
                await send_error(
                    interaction,
                    520,
                    "Failed to unmute this member due to an unknown error.",
                )
                return

        confirm_embed = build_confirm_embed(
            action_label="Unmute",
            case_id=case_id,
            action_number=unmute_number,
            member=member,
            log_url=log_url,
        )
        await interaction.response.send_message(
            embed=confirm_embed,
            ephemeral=False,
        )

    # ------------------------------
    # /unban
    # ------------------------------

    @app_commands.command(
        name="unban",
        description="Unban a user from the server.",
    )
    @app_commands.describe(
        user_id="The ID of the user to unban.",
        reason="Reason for the unban.",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def unban_cmd(
        self,
        interaction: discord.Interaction,
        user_id: str,
        reason: str,
    ):
        guild = interaction.guild
        if guild is None:
            await send_error(interaction, 500, "This command can only be used inside the server.")
            return

        if not isinstance(interaction.user, discord.Member):
            await send_error(interaction, 401, "You must be a server member to run this command.")
            return

        if not is_staff(interaction.user):
            await send_error(
                interaction,
                500,
                "You must be a staff member to use moderation commands.",
            )
            return

        if SIMULATION_MODE and not is_admin(interaction.user):
            await send_error(
                interaction,
                500,
                "This command is currently running in simulation mode. "
                "Only server administrators can use simulated moderation commands.",
            )
            return

        try:
            target_id_int = int(user_id)
        except ValueError:
            await send_error(interaction, 400, "User ID must be a valid integer.")
            return

        evidence_text = "N/A"

        case_id, unban_number = create_case(
            guild.id,
            target_id_int,
            interaction.user.id,
            "UNBAN",
            reason,
            evidence_text,
            None,
            None,
            automatic=False,
        )

        created_at = int(time.time())
        ts_str = discord_timestamp(created_at, "f")

        staff_embed = (
            discord.Embed(
                color=0x2ECC71,
                title=f"{EMOJI_OVRP1} Unban | Case #{case_id} & Unban {unban_number}",
                timestamp=datetime.datetime.utcfromtimestamp(created_at),
            )
            .set_author(
                name=str(interaction.user),
                icon_url=interaction.user.display_avatar.url,
            )
            .set_footer(text="OVRP | Moderation Systems")
        )
        staff_embed.add_field(
            name="Member",
            value=f"<@{target_id_int}> (`{target_id_int}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Moderator",
            value=f"<@{interaction.user.id}> (`{interaction.user.id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        staff_embed.add_field(
            name="Evidence",
            value=evidence_text,
            inline=True,
        )
        staff_embed.add_field(
            name="Date",
            value=ts_str,
            inline=True,
        )

        staff_channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
        if not isinstance(
            staff_channel,
            (discord.TextChannel, discord.Thread, discord.ForumChannel),
        ):
            await send_error(
                interaction,
                503,
                "Staff log channel is misconfigured. Please contact an administrator.",
            )
            return

        try:
            msg = await staff_channel.send(embed=staff_embed)
        except discord.Forbidden:
            await send_error(
                interaction,
                500,
                "I do not have permission to send messages in the staff log channel.",
            )
            return
        except discord.HTTPException:
            await send_error(
                interaction,
                520,
                "Failed to post to the staff log channel due to an unknown error.",
            )
            return

        set_case_staff_message(case_id, msg.id)
        log_url = f"https://discord.com/channels/{guild.id}/{STAFF_LOG_CHANNEL_ID}/{msg.id}"

        if not SIMULATION_MODE:
            try:
                user_obj = discord.Object(id=target_id_int)
                await guild.unban(user_obj, reason=f"[Case #{case_id}] {reason}")
            except discord.NotFound:
                await send_error(
                    interaction,
                    404,
                    "That user is not currently banned from this server.",
                )
                return
            except discord.Forbidden:
                await send_error(
                    interaction,
                    500,
                    "I do not have permission to unban that user.",
                )
                return
            except discord.HTTPException:
                await send_error(
                    interaction,
                    520,
                    "Failed to unban this user due to an unknown error.",
                )
                return

        try:
            target_user = await self.bot.fetch_user(target_id_int)
        except discord.NotFound:
            target_user = None
        except discord.HTTPException:
            target_user = None

        if target_user is not None:
            now_ts = int(time.time())
            now_dt = datetime.datetime.fromtimestamp(now_ts, datetime.timezone.utc)
            now_str = now_dt.strftime("%d/%m/%Y %I:%M %p")

            dm_embed = (
                discord.Embed(
                    color=0x2ECC71,
                    title=f"{EMOJI_CHECK} Unban processed | Case #{case_id} & Unban {unban_number}",
                    description=(
                        "Your ban for **OVRP | Oceanview Roleplay** has been lifted.\n\n"
                        "You may rejoin the server using the link below:\n"
                        "https://discord.gg/ovrp"
                    ),
                )
                .set_author(
                    name="OVRP | Moderation Notice",
                    icon_url=OVRP_LOGO_URL,
                )
                .set_image(url=BANNER_IMAGE_URL)
                .set_footer(
                    text=(
                        "This unban has been reviewed and approved by the OVRP Management Team. "
                        f"• {now_str}"
                    ),
                )
            )
            try:
                await target_user.send(embed=dm_embed)
            except Exception:
                pass

        confirm_embed = build_confirm_embed(
            action_label="Unban",
            case_id=case_id,
            action_number=unban_number,
            member=target_user if target_user is not None else interaction.user,
            log_url=log_url,
        )
        await interaction.response.send_message(
            embed=confirm_embed,
            ephemeral=False,
        )

    # ------------------------------
    # /modlogs
    # ------------------------------

    @app_commands.command(
        name="modlogs",
        description="View a user's moderation history.",
    )
    @app_commands.describe(
        user="The user to view modlogs for.",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def modlogs_cmd(
        self,
        interaction: discord.Interaction,
        user: discord.User,
    ):
        guild = interaction.guild
        if guild is None:
            await send_error(interaction, 500, "This command can only be used inside the server.")
            return

        if not isinstance(interaction.user, discord.Member):
            await send_error(interaction, 401, "You must be a server member to run this command.")
            return

        if not is_staff(interaction.user):
            await send_error(
                interaction,
                500,
                "You must be a staff member to view modlogs.",
            )
            return

        rows = fetch_cases_for_user(guild.id, user.id)
        if not rows:
            await send_error(
                interaction,
                404,
                "This user has no moderation history.",
            )
            return

        view = ModlogsView(guild.id, user, rows, owner_id=interaction.user.id)
        embed = view.create_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)


# ============================================================
# BACKGROUND TASKS (AUTOMATIC UNBAN)
# ============================================================


@tasks.loop(minutes=1)
async def unban_watcher():
    await bot.wait_until_ready()

    now_ts = int(time.time())
    expired_bans = fetch_expired_bans(now_ts)
    if not expired_bans:
        return

    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return

    for row in expired_bans:
        case_id = int(row["case_id"])
        user_id = int(row["user_id"])

        reason = "Ban was temporary"
        evidence_text = "N/A"

        bot_id = bot.user.id if bot.user else 0  # type: ignore
        auto_case_id, unban_number = create_case(
            guild.id,
            user_id,
            bot_id,
            "UNBAN",
            reason,
            evidence_text,
            None,
            None,
            automatic=True,
        )

        created_at = int(time.time())
        ts_str = discord_timestamp(created_at, "f")

        author_name = str(bot.user) if bot.user else "OVRP Bot"  # type: ignore
        author_icon = (
            bot.user.display_avatar.url  # type: ignore
            if bot.user
            else OVRP_LOGO_URL
        )

        staff_embed = (
            discord.Embed(
                color=0x2ECC71,
                title=f"{EMOJI_OVRP1} Automatic Unban | Case #{auto_case_id}",
                timestamp=datetime.datetime.utcfromtimestamp(created_at),
            )
            .set_author(
                name=author_name,
                icon_url=author_icon,
            )
            .set_footer(text="OVRP | Moderation Systems")
        )
        staff_embed.add_field(
            name="Member",
            value=f"<@{user_id}> (`{user_id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Moderator",
            value=f"{author_name} (`{bot_id}`)",
            inline=True,
        )
        staff_embed.add_field(
            name="Reason",
            value=reason,
            inline=False,
        )
        staff_embed.add_field(
            name="Evidence",
            value=evidence_text,
            inline=True,
        )
        staff_embed.add_field(
            name="Date",
            value=ts_str,
            inline=True,
        )

        staff_channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
        if isinstance(
            staff_channel,
            (discord.TextChannel, discord.Thread, discord.ForumChannel),
        ):
            try:
                msg = await staff_channel.send(embed=staff_embed)
                set_case_staff_message(auto_case_id, msg.id)
            except discord.Forbidden:
                logger.warning(
                    "Missing permission to send automatic unban logs in staff channel."
                )
            except discord.HTTPException:
                logger.warning(
                    "HTTP error while sending automatic unban logs for user %s", user_id
                )

        mark_case_auto_unban_done(case_id)

        if not SIMULATION_MODE:
            try:
                user_obj = discord.Object(id=user_id)
                await guild.unban(
                    user_obj,
                    reason="[Automatic Unban] Temporary ban expired.",
                )
            except discord.NotFound:
                continue
            except discord.Forbidden:
                logger.warning(
                    "Missing permission to auto-unban user %s (case %s)",
                    user_id,
                    case_id,
                )
            except discord.HTTPException:
                logger.warning(
                    "HTTP error while auto-unbanning user %s (case %s)",
                    user_id,
                    case_id,
                )


# ============================================================
# GLOBAL APP COMMAND ERROR HANDLER
# ============================================================


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    logger.exception("Unhandled app command error: %r", error)
    try:
        await send_error(
            interaction,
            520,
            "An unexpected error occurred while running this command.",
        )
    except Exception as e:
        logger.warning("Failed to send global error response: %s", e)


# ============================================================
# EVENT HOOKS / STARTUP
# ============================================================


@bot.event
async def on_connect():
    logger.info("Bot connected to Discord gateway.")
    if not unban_watcher.is_running():
        try:
            unban_watcher.start()
            logger.info("Started automatic unban watcher task.")
        except RuntimeError as e:
            logger.warning("Could not start unban watcher yet: %s", e)


# ============================================================
# MAIN ENTRYPOINT
# ============================================================


async def main() -> None:
    init_db()
    await bot.add_cog(Moderation(bot))
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
