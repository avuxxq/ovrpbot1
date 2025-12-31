SPEC_APPEALS.md (your exact “do this” spec)

Copy/paste this verbatim so Codex treats it as non-negotiable.

Non-Negotiable Rules --
❌ Do not change moderation command UI/UX or embed layouts unless explicitly requested.
❌ Do not rename commands or remove commands.
✅ All appeal embeds must match the exact text/format/bold/emoji usage below.
✅ Use these custom emojis where applicable:
<:OVCross:1455159223972397212> - ❌ cross
<:OVCheck:1455159291739635722> - ✅ checkmark
<:OVRP1:1455159417497583818> - OVRP logo
<:OVWait:1455159556790423654> - 🕒 clock

Appeal Button Placement --
The Appeal button appers on the ban DM embed only when:
Ban is permanent (0 days), OR
Ban duration is more than 4 days.
For bans of 4 days or less, no appeal button.

Appeal Timing Logic --
If ban is appealable:
User can appeal after 72 hours (3 days).
When user clicks appeal before 72h:
Bot replies ephemerally with the “Appeal not yet available” message.
Do not include absolute time in brackets. Only show relative countdown.

SIMULATION_MODE ON:
No timer gate at all. Appeal proceeds instantly.
Duplicate / Closed Appeals
If an appeal for the same ban/case is already ACCEPTED or CLOSED, user cannot submit another.
If an appeal is PENDING, user cannot submit another.
If appeal is DENIED, user may submit another appeal after 72 hours (cooldown), unless SIMULATION_MODE is on.

Appeal Modal (User)
When user clicks appeal:
Modal with 3 inputs:

ROBLOX Username
Why would you like to get unbanned?
Is there extra information you’d like to give?

Appeals Channel
Appeals are posted to: 1455122904072323256
Staff controls: Approve / Reject / Request more Information / View History
Only admins can action.
“Request more Information” Flow
Staff clicks “Request more Information”
Modal asks staff for a question
Bot DMs user the More Information Required embed + Respond button
User clicks Respond → modal to answer
Answer is posted back to appeals channel as:
“Appeal update - Additional Information Received | ID: A-xxx”
Followed by the “More Information Required” embed if needed.

Required Embed Formats (EXACT)

Use these exact values (text, bolding, emojis, punctuation, line breaks):
