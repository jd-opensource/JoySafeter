---
name: Scene Classifier
description: Classify user input into appropriate scene type
usage_context: agent/prompts
purpose: Determine which scene mode the agent should use
version: "3.0.0"
variables:
  - user_input
---

<task>
Classify the user input into one of the following scene types.
This determines which specialized system prompt to use.
</task>

<input>
User input: {user_input}
</input>

<scenes>
<scene name="ctf">
CTF (Capture The Flag) cybersecurity competition:
- Mentions CTF, flag, capture the flag, FLAG
- Practice/challenge on specific URL or port
- Involves decryption, decoding, reverse engineering
- Mentions pwn, web challenge, crypto, misc, forensics
- Requests connection via nc/netcat to an address
- Seeks hidden flag or vulnerability exploitation for learning
</scene>

<scene name="general">
General tasks (default):
- General programming or coding tasks
- Everyday questions
- Non-security related work
</scene>
</scenes>

<output_format>
IMPORTANT: Output ONLY one of: "ctf", "general"
No explanation, just the scene name.
</output_format>
