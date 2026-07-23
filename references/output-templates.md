# Output Templates

## Daily scan digest

```md
# Daily Literature Scan
Coverage: YYYY-MM-DD to YYYY-MM-DD
Profile: <profile-name>

## Must Read
| Priority | Class | Journal | Paper | Why it matters | Pool source | Rank basis | Action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | A | Journal Name | Paper Title | Core-topic fit + method/data value | top-family seed | top-family seed; ranking pending | Add to queue |

## Should Read
| Priority | Class | Journal | Paper | Why it matters | Pool source | Rank basis | Action |
| --- | --- | --- | --- | --- | --- | --- | --- |

## Watchlist
| Class | Journal | Paper | Signal | Pool source | Rank basis | Next step |
| --- | --- | --- | --- | --- | --- | --- |

## Carry-Over Reminders
- Paper title: pending for X days because it is high relevance and still unread.

## Boundary Review
- Boundary paper:
- Why it is not core to the active profile:
- Whether it still informs proxy evaluation or concept differentiation:
```

## Weekly Monday report

```md
# Weekly Frontier Tracking Report
Coverage: YYYY-MM-DD to YYYY-MM-DD
Profile: <profile-name>

## Executive View
- New papers screened:
- Must read this week:
- Papers already noted:
- Overdue high-priority papers:

## Must Read
| Class | Priority | Journal | Paper | Why now | Pool source | Rank basis | Suggested note |
| --- | --- | --- | --- | --- | --- | --- | --- |

## Should Read
| Class | Priority | Journal | Paper | Relevance signal | Action |
| --- | --- | --- | --- | --- | --- |

## Methods and Data Signals
- Method or dataset:
- Why it is reusable:

## Themes This Week
- Theme:
- Supporting papers:
- Why it matters to the profile:

## Boundary and Proxy Paths
- Concept:
- Representative paper:
- Why it is boundary rather than core:
- Whether it helps clarify the core mechanism under study:

## Action List
- Read:
- Note:
- Archive or skip:
```

## Reading queue status

- `to-screen`: newly found and not yet triaged.
- `queued`: selected for reading soon.
- `reading`: currently in progress.
- `noted`: summarized into Zotero or Obsidian.
- `archived`: intentionally stored with no immediate action.
- `skip`: intentionally ignored.

## Obsidian note template

```md
---
title: "<paper-title>"
journal: "<journal-name>"
published: "YYYY-MM-DD"
doi: "<doi>"
rank_basis: "CAS 1 / JCR Q1"
pool_source: "top-family seed"
relevance: "high"
topics: ["topic-1", "topic-2"]
status: "noted"
A_F_class: "A"
P1_P3_priority: "P1"
directness: "core"
boundary_or_proxy: "none"
county_scale_relevance: "high"
concept_warning: ["none"]
---

# Citation
<full citation>

# Basic Metadata
- Study object:
- Scale:
- Data:
- Method:

# Why It Matters
- One-sentence relevance summary.

# Key Findings
- Finding 1
- Finding 2

# Limitations
- Limitation 1

# Methods or Data
- Method:
- Dataset:

# Concept Boundary Check
- Treats land-use types as direct mechanisms (vs. instruments or controls):
- Treats spatial/concentration measures as causal pathways (vs. outcomes):
- Uses proxy indicators for the core phenomenon:

# Use For My Work
- Reusable idea:
- Limitation:
- Follow-up:
```

## Zotero note template

```md
Summary: One-paragraph plain-language summary.

Classification:
- A-F class:
- P1-P3 priority:
- Directness to core mechanism:
- Boundary or proxy status:
- Spatial/policy applicability:

Basic metadata:
- Study object:
- Scale:
- Data:
- Method:

Why relevant:
- Core fit:
- Method fit:
- Geography or system fit:

Key extractable points:
- Point 1
- Point 2

Concept boundary check:
- Land-use types treated as direct mechanisms:
- Spatial/concentration measures treated as causal pathways:
- Proxy indicators presented as direct measures:

Next action:
- Read in full / cite / archive / compare with <paper>.
```

## A-F classification scheme (public economics / urban economics / housing)

- `A`: direct theory, definition, or conceptual boundary of the core mechanism under study (e.g., housing voucher effects on labor mobility, spatial mismatch of skills in cities, fiscal competition dynamics).
- `B`: conceptual framework or policy design literature that informs the theoretical structure (e.g., welfare program design, optimal tax theory, urban land policy).
- `C`: direct measurement, index design, or estimation methodology for the core phenomenon (e.g., measuring skill mismatch, housing affordability indices, public goods provision metrics).
- `D`: empirical spatial or cross-sectional assessment where the core phenomenon is the explicit target (e.g., city-level skill mismatch and wages, inter-city housing price spillovers).
- `E`: applied policy evaluation with the core phenomenon as the primary object (e.g., causal effects of housing subsidies, place-based policies, public insurance programs).
- `F`: boundary, proxy, or adjacent-concept literature that informs differentiation but is not core ontology (e.g., related labor market policies without housing dimension, general equilibrium models without spatial component).

## P1-P3 priority scheme

- `P1`: core reading to keep up with immediately, because it directly affects the active tracking focus and should enter the reading queue first.
- `P2`: useful supporting reading, methods transfer, or boundary clarification.
- `P3`: background context, weakly related material, or low-value watchlist items.
