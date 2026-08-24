# ReAct Pattern Implementation

## Overview

Poisonarr uses the **ReAct (Reasoning + Acting)** pattern for browser automation via **LangChain**. This is a standard LLM agent architecture where the agent iteratively:

1. **Observes** the current state (via accessibility snapshot)
2. **Reasons** about what action to take (LLM decides)
3. **Acts** on the environment (Playwright executes)
4. **Repeats** until goal is achieved

## LangChain Integration

Built on LangChain's `create_react_agent` with:
- **ConversationSummaryBufferMemory** - Automatic context compression
- **Custom Playwright Tools** - Browser actions as LangChain tools
- **Token Tracking Callbacks** - Usage stats for monitoring UI
- **Accessibility Snapshots** - Semantic page structure for LLM

## Why ReAct?

Traditional browser automation is **scripted** - you write exact steps ahead of time. This breaks when:
- Pages have different layouts
- Captchas or cookie banners appear
- Content loads dynamically
- Sites change their structure

ReAct agents are **reactive** - they observe the actual page and decide what to do based on what's there. This makes them:
- More robust to page variations
- Able to handle unexpected situations (captchas, popups)
- More human-like in behavior

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         ReAct Loop                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────┐     ┌──────────┐     ┌──────────┐                │
│   │ OBSERVE  │────▶│  REASON  │────▶│   ACT    │                │
│   │          │     │  (LLM)   │     │          │                │
│   └──────────┘     └──────────┘     └──────────┘                │
│        ▲                                  │                      │
│        │                                  │                      │
│        └──────────────────────────────────┘                      │
│                    (repeat)                                      │
│                                                                  │
│   Terminal States: DONE or FAIL                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Observation (`get_observation`)

We use Playwright's **accessibility snapshot** to get the page structure:

```python
snapshot = await page.accessibility.snapshot()
```

This returns a tree of accessible elements:
```
[heading] "Welcome to Amazon"
  [link] "Sign In"
  [searchbox] "Search"
  [button] "Search"
  [list] "Categories"
    [listitem] "Electronics"
    [listitem] "Books"
```

This is much more compact than full HTML and contains the semantic structure the LLM needs.

### 2. Reasoning (`decide_action`)

The LLM receives:
- **Goal**: What we're trying to accomplish
- **Current URL/Title**: Where we are
- **Page Structure**: Accessibility snapshot
- **Recent History**: Last 5 actions taken

It outputs a JSON action:
```json
{
  "action": "click",
  "selector": "button:has-text('Search')",
  "reasoning": "clicking search button to find products"
}
```

### 3. Action Execution (`execute_action`)

Available actions:

| Action   | Description                | Example                              |
|----------|----------------------------|--------------------------------------|
| `click`  | Click an element           | `{"action": "click", "selector": "[aria-label='Search']"}` |
| `type`   | Type into a field          | `{"action": "type", "selector": "input[name='q']", "value": "laptops"}` |
| `scroll` | Scroll the page            | `{"action": "scroll", "value": "down"}` |
| `goto`   | Navigate to URL            | `{"action": "goto", "value": "https://amazon.com"}` |
| `back`   | Go back                    | `{"action": "back"}` |
| `wait`   | Wait seconds               | `{"action": "wait", "value": "2"}` |
| `done`   | Goal complete              | `{"action": "done", "reasoning": "found the product"}` |
| `fail`   | Cannot complete            | `{"action": "fail", "reasoning": "hit login wall"}` |

## Handling Special Situations

### Captchas

The accessibility snapshot shows captcha elements:
```
[iframe] "reCAPTCHA"
  [checkbox] "I'm not a robot"
```

The LLM is instructed to:
1. Click checkbox captchas directly
2. Report image captchas as blockers
3. Move on if stuck

### Cookie Banners

```
[dialog] "Cookie Consent"
  [button] "Accept All"
  [button] "Customize"
```

LLM clicks "Accept" and continues.

### Login Walls

LLM recognizes login requirements and uses `fail` action to move to next site.

## Timeout Protection

Multiple layers prevent hanging:

| Level          | Timeout | Purpose                    |
|----------------|---------|----------------------------|
| Step           | 30s     | Single action execution    |
| LLM            | 20s     | Waiting for LLM response   |
| Agent Run      | 90s     | Complete goal attempt      |
| Session        | 180s    | Entire browsing session    |

Consecutive failures (3+) also trigger early exit.

## Code Structure

```
poisonarr/
├── langchain_agent.py    # LangChain ReAct agent
│   ├── BrowserAgent      # Main agent (uses create_react_agent)
│   ├── BrowserTools      # Playwright tools for LangChain
│   └── TokenTrackingCallback  # Token usage tracking
│
├── memory.py             # Progressive summarization
│   ├── MemoryManager     # Persistent memory storage
│   ├── AgentMemory       # Long-term agent memory
│   └── SessionMemory     # Single session memory
│
├── session.py            # Session management
│   ├── SessionManager    # Generates intents, runs agent
│   └── BrowsingIntent    # Browsing goal specification
│
├── server.py             # Monitoring UI with stats
│   ├── UIServer          # WebSocket server
│   ├── AgentState        # Agent status tracking
│   └── AgentStats        # Token/action statistics
│
├── prompts/              # External prompt files
│   ├── tools_schema.md   # Browser action definitions
│   ├── intent_generation.md  # Persona/goal generation
│   └── memory_summary.md # Memory summarization
│
└── agent.py              # Main loop
    └── PoisonarrAgent    # Orchestrates sessions
```

## Example Session Flow

1. **Generate Intent**:
   ```
   Persona: "A 32-year-old teacher looking for science kits"
   Goal: "Find educational science kits for middle school students"
   Starting Point: "amazon.com"
   ```

2. **Agent Run**:
   ```
   Step 1: OBSERVE page → Amazon homepage
          REASON → Need to search for science kits
          ACT → type "science kits middle school" in search box

   Step 2: OBSERVE page → Search results
          REASON → Found products, should browse
          ACT → scroll down

   Step 3: OBSERVE page → More products visible
          REASON → See interesting product
          ACT → click on "National Geographic Science Kit"

   Step 4: OBSERVE page → Product detail page
          REASON → Good product found, goal achieved
          ACT → done
   ```

## Extending the Agent

### Adding New Actions

1. Add to `ActionType` enum
2. Add case in `execute_action`
3. Document in `TOOLS_SCHEMA` prompt

### Improving Observations

The accessibility snapshot can be enhanced with:
- Screenshots (for vision LLMs)
- Console logs
- Network requests
- DOM mutations

### Multi-Tab Support

Currently single-tab. Could extend with:
- Tab tracking in observation
- `new_tab` and `switch_tab` actions

## References

- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
- [Playwright Accessibility](https://playwright.dev/docs/accessibility-testing)
- [LangChain Agents](https://python.langchain.com/docs/modules/agents/)
- [smolagents](https://huggingface.co/docs/smolagents/)
