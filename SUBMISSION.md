# trace - VideoDB Hackathon Submission

## 200-word description

trace gives your pull requests a memory. It watches your entire coding session, screen, voice, terminal, AI interactions, and builds a living record of how your code was actually written.

When you open a PR, trace generates a narrated walkthrough video using real clips from your session and your own spoken reasoning, not just the diff. It posts this directly to your PR alongside a context-aware description explaining what changed, why, what you struggled with, and what needs follow-up.

The session memory stays alive. Reviewers can ask `@trace` any question on the PR; trace runs semantic search across the indexed spoken-word and scene indexes and replies with a text answer plus up to three bounded clip URLs from your session. A Decision Replay page lets reviewers pick any file and line range and watch the recorded moments when those lines were edited.

trace also generates a Human vs Agent contribution map by scanning Claude Code session logs scoped to the capture window, classifying each PR line as human, agent, mixed, or unknown.

Built entirely on VideoDB: capture (chunked upload during recording), `index_scenes` + `index_spoken_words`, semantic search, `generate_text`, `generate_voice`, and `videodb.editor.Timeline` with three composed tracks.

## Demo flow

1. `trace start --project /path/to/repo` records a real coding session.
2. `trace stop` uploads + indexes + builds timeline.
3. `trace generate <session> <pr_url>` posts narrated video + contribution map + description.
4. `trace serve` opens Decision Replay UI.
5. `@trace why did you remove the cache?` in a PR comment triggers semantic search + reply.

## Repository

<github-url-here>

## Walkthrough video

<demo-video-url-here>
