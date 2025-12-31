
You are editing an existing Discord bot codebase.
You MUST NOT change any existing command names, command behavior, UI/UX layouts, or embed layouts except for the appeal system requirements defined in SPEC_APPEALS.md.

Implement the appeal system exactly as described in SPEC_APPEALS.md, including:

Eligibility rules (perm or >4 days only)

72h wait and 72h denial cooldown (disabled when SIMULATION_MODE = True)

Prevent re-appeals if already ACCEPTED/CLOSED and prevent duplicates if PENDING

Staff workflow: Approve/Reject/Request more info/View history

DM and staff embeds must match the exact formatting from SPEC_APPEALS.md (text, bold, emojis, punctuation, line breaks)

Use the custom emojis exactly:
<:OVCross:1455159223972397212>, <:OVCheck:1455159291739635722>, <:OVRP1:1455159417497583818>, <:OVWait:1455159556790423654>

Do not simplify UI. Do not remove code unless it is breaking.
Return the full updated file(s) with no placeholders.
