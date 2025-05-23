# News Firehose — Monolith v1.3 Design Document

> **Status**: **DRAFT‑v1.3** – *21 May 2025* (consolidated)

This version folds the community‑interaction additions from **v1.2** into the full **v1.1** specification so everything lives in a single, self‑contained document.

---

## 0 · Change Log

| Date       | Version | Author     | Notes                                                                                   |
| ---------- | ------- | ---------- | --------------------------------------------------------------------------------------- |
| 2025‑05‑21 | v1.3    | ChatGPT‑o3 | **Merged v1.1 core with v1.2 community tools** (chat summariser & DeToxify moderation). |
| 2025‑05‑21 | v1.2    | ChatGPT‑o3 | Added community summariser & toxicity guard diff.                                       |
| 2025‑05‑21 | v1.1    | ChatGPT‑o3 | Replaced `biasNotes` with `sourceBias`; minor caching & health‑check notes.             |
| 2025‑05‑20 | v1.0    | ChatGPT‑o3 | Initial monolith design.                                                                |

---

## 1 · Executive Summary

News Firehose ingests diverse news sources, converts them into **Events** enriched with LLM‑generated summaries, tags, balanced interpretations, and **source‑bias transparency**.  Events flow to Discord and a public website; weekly & monthly recap jobs synthesise broader narratives.  New community features allow users to ask for channel/thread summaries (≤48 h) and enforce civility with an on‑the‑fly DeToxify moderation guard.  Everything runs in one Node/TypeScript service plus MongoDB, yet boundaries are clear for later micro‑splitting.

---

## 2 · High‑Level Architecture

| Layer                | Responsibility                                         | Key Libs / APIs                    |
| -------------------- | ------------------------------------------------------ | ---------------------------------- |
| **Ingestion Worker** | Polls sources, parses raw items, de‑dupes              | `rss‑parser`, custom fetchers      |
| **Event Processor**  | LLM summarisation, tagging, **source‑bias extraction** | `openai`, `langchain`              |
| **Scheduler**        | Weekly/monthly recap cron jobs                         | `node‑schedule`                    |
| **Discord Adapter**  | Publishes Events, creates Q\&A threads                 | `discord.js` / `discord.py`        |
| **Community Tools**  | ✨ Chat summariser cmd & DeToxify moderation            | `discord.js`, `detoxify`, `openai` |
| **HTTP Server**      | Public Next.js site + admin portal                     | `next.js`, `express`, `adminjs`    |
| **Chat‑RAG Service** | Vector search over Events for site Q\&A                | MongoDB Atlas Vector Search        |
| **DB**               | MongoDB single‑node replica                            | TTL & time‑series design           |

```
          ┌─────────────────────────────────────────┐
          │              App Monolith              │
          │  Node 20 process (PM2)                 │
DB <──────┤  • Ingestion / Processor               │
(Mongo)   │  • Scheduler                           │
          │  • Discord Adapter                     │
          │  • Community Tools (summariser/mod)    │
          │  • Express / Next.js                   │
          └─────────────────────────────────────────┘
```

All layers share one MongoDB client; health‑checks and graceful shutdown unify lifecycle.

---

## 3 · MongoDB Schema

### 3.1 `events`

```javascript
{
  _id: ObjectId,
  sourceId:   ObjectId,
  guid:       String,        // source‑unique key
  title:      String,
  summary:    String,        // LLM abstract with citations
  content:    String,        // optional full‑text
  tags:       [String],      // e.g. ["US‑Politics","Climate"]
  sourceBias: {
    sources: [{ name: String, bias: String }], // list of author/outlet + stance
    blurb: String                              // ≤280 chars plain‑text
  },
  interpretations: {           // optional multi‑frame viewpoints
    leftFrame:  String,
    rightFrame: String
  },
  publishedAt: ISODate,
  createdAt:   ISODate
}
// indexes
//  guid unique, (tags,publishedAt) compound, text index on title+summary
```

### 3.2 `embeddings`

```javascript
{ _id: ObjectId, eventId: ObjectId, vector: [Number] }
```

### 3.3 `summaries` (chat summariser cache)

```javascript
{
  _id: ObjectId,
  channelId:   String,      // channel / thread / forum ID
  windowStart: ISODate,
  windowEnd:   ISODate,
  summary:     String,
  createdAt:   ISODate       // TTL: 72 h
}
```

### 3.4 `moderation_logs` (optional, capped)

```javascript
{
  _id: ObjectId,
  flaggedAt: ISODate,
  channelId: String,
  userId:    String,
  toxicity:  String,    // class (e.g. "threat")
  action:    String,    // DELETE / IGNORE
  reason:    String     // GPT justification (≤200 chars)
}
```

---

## 4 · Event Processing Pipeline

1. **Ingest** raw items, dedupe on `{sourceId,guid}`.
2. **LLM function call** returns `summary`, `tags`, `sourceBias`, `interpretations`.
3. Insert into `events`; asynchronously compute and store `embedding`.

*(Prompt details unchanged from v1.1)*

---

## 5 · Recap Generator

Weekly (Sun 23:55 UTC) and monthly (last day 23:55 UTC) jobs cluster Events by tag and request GPT to create Markdown recaps that include an aggregated **Source & Bias** appendix.

---

## 6 · Discord Bot Flow

1. **Post** each Event embed to channels mapped to ≥1 tag.
2. **Thread** created for Q\&A; OpenAI assistant thread frozen with Event context.
3. Bot replies only when mentioned inside that thread.
4. Discord embed hides `sourceBias`; website exposes it.

---

## 7 · Website & Admin

* Next.js SSR site: `/`, `/tags/[tag]`, `/event/[id]`, `/recap/[date]`, `/post/[id]`.
* Event view shows **Source & Bias** accordion and Balanced‑Lens tab.
* Admin portal (`adminjs`) supports: CRUD posts, “Generate Long‑Form” button, recap review.
* Site chat uses Vector‑RAG over `events` + `openai` for answers.

---

## 8 · Community Interaction Features

### 8.1 Chat Summariser Command

* **Command**: `!summarise [hours]` (1‑48 h).
* Works in channels, threads, forum posts.
* Pipeline:

  1. Permission & rate‑limit (3 calls / 10 min / user).
  2. Fetch history via `ctx‑utils.getHistory`.
  3. Render to markdown using YWCC‑RG‑Bot template.
  4. Ask GPT‑4o for ≤300‑word summary + bullet list of open questions.
  5. Reply with embed; cache in `summaries`.

### 8.2 DeToxify Moderation Guard

* **Model**: Unitary AI DeToxify Tiny‑BERT.
* **Workflow**:

  1. On `messageCreate`, score content.
  2. If any class ≥ `TOX_THRESHOLD`:

     * Grab prior 5‑minute context via `ctx‑utils.getContext`.
     * LLM check: decide **DELETE** vs **IGNORE**.
     * If `DELETE`: delete message, DM user copy + static notice.
  3. Optionally insert record in `moderation_logs`.

### 8.3 `ctx‑utils.ts` Shared Helper

```ts
export async function getHistory(
  chan: TextBasedChannel | ThreadChannel | ForumChannel,
  since: Date
): Promise<Message[]> { /* polyfill over .messages.fetch */ }

export async function getContext(
  msg: Message,
  rangeMs = 5 * 60 * 1000
): Promise<Message[]> { /* fetch around msg.timestamp‑range */ }
```

---

## 9 · Balanced‑Bias Framework

1. **Source Transparency** – surfaced via `sourceBias`.
2. **Interpretation Frames** – optional left/right/worldview summaries.
3. **UI** – Bias accordion + Balanced‑Lens toggle on site; neutral embed in Discord.

---

## 10 · Security, Privacy & Rate‑Limits

* Summariser rate‑limited (express‑rate‑limit middleware).
* Moderation logs capped & scrub personally identifiable content after 30 days.
* All user prompts run through `openai.moderations`.
* OAuth (NextAuth) for admin; 2FA recommended.

---

## 11 · Deployment

* Single Ubuntu 22.04 VM; Docker Compose with `mongo:6` and Node app.
* DeToxify adds ≈200 MB RAM; GPU optional.
* PM2 inside container; health‑check `/healthz` (uptime & last‑loop timestamps).

---

## 12 · Future Work

* Move Community Tools into separate microservice once message volume > 50 msg/s.
* Redis cache for embeddings & YWCC‑RG style history renders.
* OpenTelemetry tracing across LLM chains.

---

## References

1. **Discord Thread API** (<docs>), 2. **OpenAI Assistants** (<docs>), 3. **MongoDB Time‑Series** (<docs>)…
2. **YWCC‑RG‑Bot** formatter [https://github.com/Bytestorm5/YWCC-RG-Bot](https://github.com/Bytestorm5/YWCC-RG-Bot)
3. **Detoxify** [https://github.com/unitaryai/detoxify](https://github.com/unitaryai/detoxify)
   (Full citation list maintained separately.)

