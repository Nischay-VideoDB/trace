# Requirements Document

## Introduction

Trace is a command-line tool that observes a developer's coding session by capturing screen and microphone audio, indexes the captured session into a searchable timeline of tagged moments, generates a short narrated pull request (PR) video from session highlights, and answers reviewer questions using the session's stored context. The tool integrates with VideoDB for capture, indexing, and timeline operations, OpenAI for transcription and narration, Anthropic for intent and uncertainty extraction, and the GitHub API for posting PR artifacts.

This document captures the functional and quality requirements for the Trace CLI feature, including session capture, timeline building, PR video generation, decision replay, reviewer Q&A, human-versus-agent contribution mapping, reviewer focus mode, and PR description generation.

## Glossary

- **Trace_CLI**: The command-line interface that exposes the `start`, `stop`, and `generate` subcommands and orchestrates capture, indexing, and PR generation.
- **Capture_Session**: A single recording lifecycle that begins on `trace start` and ends on `trace stop`, containing a screen video stream, a microphone audio stream, and associated metadata.
- **Capture_Service**: The component responsible for streaming screen and microphone data to VideoDB using the VideoDB CaptureSession and RTStream APIs.
- **Fallback_Capture**: The local capture mechanism using the `mss` library for screen frames and the `pyaudio` library for microphone audio, used when the VideoDB streaming endpoint is unavailable.
- **Timeline_Builder**: The component that consumes an indexed Capture_Session and produces a Timeline of Tagged_Moments.
- **Timeline**: An ordered, time-stamped sequence of Tagged_Moments derived from a Capture_Session.
- **Tagged_Moment**: A bounded time interval in a Capture_Session annotated with one of the moment categories: `stuck`, `research`, `progress`, or `speech`.
- **Stuck_Moment**: A Tagged_Moment in which the developer shows no code change progress for at least 90 seconds combined with signals of uncertainty in speech or repeated context switching.
- **Research_Moment**: A Tagged_Moment in which the active screen content is identified as documentation, search results, or external reference material.
- **Progress_Moment**: A Tagged_Moment in which code edits are committed to the editor buffer or saved to disk.
- **Speech_Moment**: A Tagged_Moment in which the microphone audio contains transcribed speech with at least 3 words.
- **PR_Video_Generator**: The component that assembles a narrated 90-second PR_Video from selected clips of a Capture_Session.
- **PR_Video**: A rendered MP4 video, no longer than 90 seconds, containing selected session clips and synthesized narration.
- **Decision_Replay**: A view that, given a code block reference, returns the contiguous Capture_Session segments where that code block was created or modified.
- **Reviewer_QA**: The component that answers natural-language reviewer questions by performing semantic search against the indexed Capture_Session and returning text answers with linked session clips.
- **Contribution_Map**: A per-line annotation over the PR diff identifying each line as `human`, `agent`, `mixed`, or `unknown` based on session evidence.
- **Focus_Mode**: A reviewer-facing presentation that filters the PR diff to the files and ranges flagged as high-risk or high-change in the Capture_Session.
- **PR_Description_Generator**: The component that produces the GitHub PR description text from the Capture_Session, including a "what" summary and a "why" rationale section.
- **VideoDB**: The external service providing CaptureSession, RTStream, indexing, semantic search, and Timeline APIs.
- **Session_Store**: The local on-disk store under `~/.trace/sessions/{session_id}/` that holds session metadata, transcripts, timeline data, and generated artifacts.

## Requirements

### Requirement 1: Start a Capture Session

**User Story:** As a developer, I want to start a screen and microphone capture session from the command line, so that my coding work is recorded for later PR generation.

#### Acceptance Criteria

1. WHEN the user runs `trace start`, THE Trace_CLI SHALL create a new Capture_Session with a unique session identifier in UUID v4 format and persist metadata to the Session_Store containing at minimum the session identifier, the start timestamp in ISO 8601 UTC format, the `capture_mode` value, and the `mic_status` value.
2. WHEN a new Capture_Session is created, THE Capture_Service SHALL open a VideoDB CaptureSession and begin streaming screen frames at a rate of at least 15 frames per second and microphone audio at a sample rate of at least 16,000 Hz over VideoDB RTStream.
3. WHEN `trace start` succeeds, THE Trace_CLI SHALL print the session identifier and the absolute local Session_Store path on separate lines to standard output and exit with status code 0.
4. IF a Capture_Session is already active when the user runs `trace start`, THEN THE Trace_CLI SHALL exit with a non-zero status code, SHALL print a message identifying the active session identifier to standard error, and SHALL NOT create a new Capture_Session.
5. IF the VideoDB RTStream endpoint cannot be reached within 10 seconds, THEN THE Capture_Service SHALL switch to Fallback_Capture using `mss` for screen frames and `pyaudio` for microphone audio and SHALL record a `capture_mode` value of `fallback` in the Capture_Session metadata.
6. IF microphone access is denied by the operating system, THEN THE Capture_Service SHALL continue capturing screen video, SHALL record a `mic_status` value of `denied` in the Capture_Session metadata, and SHALL print a warning message indicating microphone access was denied to standard error.
7. WHILE a Capture_Session is active, THE Capture_Service SHALL write a heartbeat entry to the Session_Store at intervals not greater than 5 seconds containing the elapsed capture duration in seconds and the current byte counts for the screen stream and the audio stream.
8. IF the Session_Store path is not writable when the user runs `trace start`, THEN THE Trace_CLI SHALL exit with a non-zero status code within 5 seconds, SHALL print a message indicating the Session_Store path is not writable to standard error, and SHALL NOT open a VideoDB CaptureSession or any Fallback_Capture stream.

### Requirement 2: Stop a Capture Session and Trigger Processing

**User Story:** As a developer, I want to stop the active capture session from the command line, so that the recording is finalized and processing begins.

#### Acceptance Criteria

1. WHEN the user runs `trace stop` and an active Capture_Session exists, THE Trace_CLI SHALL signal the Capture_Service to close the active VideoDB CaptureSession and flush all buffered screen and audio data within 30 seconds.
2. WHEN the Capture_Service has flushed all buffered data, THE Trace_CLI SHALL update the Capture_Session metadata with a `stopped_at` UTC timestamp and a `status` value of `processing`.
3. WHEN a Capture_Session enters `processing` status, THE Trace_CLI SHALL submit the session to VideoDB for indexing.
4. WHEN a Capture_Session enters `processing` status, THE Trace_CLI SHALL request a transcription of the microphone audio using OpenAI Whisper.
5. WHEN VideoDB indexing and Whisper transcription have both completed successfully, THE Trace_CLI SHALL update the Capture_Session `status` value to `indexed` and print a confirmation message to standard output identifying the session.
6. IF the user runs `trace stop` and no Capture_Session with status `recording` exists, THEN THE Trace_CLI SHALL exit with a non-zero status code and print a message to standard error stating that no active session exists.
7. IF Whisper transcription fails on all attempts (1 initial attempt plus up to 3 retries with exponential backoff starting at 1 second and doubling each retry), THEN THE Trace_CLI SHALL set the Capture_Session `status` value to `transcription_failed` and print an error message to standard error indicating the transcription failure.
8. IF VideoDB indexing fails, THEN THE Trace_CLI SHALL set the Capture_Session `status` value to `indexing_failed`, print the VideoDB error message to standard error, and exit with a non-zero status code.

### Requirement 3: Build a Tagged Timeline

**User Story:** As a developer, I want the captured session to be indexed into a timeline of tagged moments, so that I can review what happened during the session by category.

#### Acceptance Criteria

1. WHEN a Capture_Session reaches `indexed` status, THE Timeline_Builder SHALL produce a Timeline whose Tagged_Moments are non-overlapping and contiguously cover the Capture_Session from start_seconds 0 to the session end_seconds with zero gaps.
2. THE Timeline_Builder SHALL classify each Tagged_Moment as exactly one of `stuck`, `research`, `progress`, or `speech`.
3. WHEN the Capture_Session contains a contiguous interval of at least 90 seconds and at most 1800 seconds with no editor file save event and at least one transcript segment flagged as expressing uncertainty by the Anthropic classifier, THE Timeline_Builder SHALL emit a `stuck` Tagged_Moment for that interval.
4. WHEN the foreground operating system window in a Capture_Session interval of at least 15 seconds is classified by VideoDB indexing as documentation, browser search results, or non-editor reference material, AND the foreground window is not the code editor window, THE Timeline_Builder SHALL emit a `research` Tagged_Moment for that interval.
5. WHEN the Capture_Session contains an editor file save event at time T seconds, THE Timeline_Builder SHALL emit a `progress` Tagged_Moment covering the interval from max(0, T-5) seconds to min(session_end_seconds, T+5) seconds.
6. WHEN the transcribed audio for a Capture_Session interval of at least 1 second and at most 60 seconds contains at least 3 words, THE Timeline_Builder SHALL emit a `speech` Tagged_Moment for that interval with the transcript text attached to the `evidence` field.
7. THE Timeline_Builder SHALL persist the Timeline to the Session_Store as a JSON file named `timeline.json` and SHALL register the Timeline with the VideoDB Timeline API.
8. THE Timeline_Builder SHALL serialize each Tagged_Moment with the fields `start_seconds` (non-negative number), `end_seconds` (number greater than `start_seconds`), `category` (one of `stuck`, `research`, `progress`, `speech`), `confidence` (decimal from 0.0 to 1.0 inclusive), and `evidence` (string).
9. THE Timeline_Builder SHALL ensure that parsing any persisted `timeline.json` file then serializing the resulting Timeline then parsing it again produces an equivalent Timeline (round-trip property).
10. IF two or more of criteria 3 through 6 match the same Capture_Session interval, THEN THE Timeline_Builder SHALL emit a single Tagged_Moment for that interval using the priority order progress > stuck > research > speech.
11. IF no rule from criteria 3 through 6 matches a contiguous Capture_Session interval, THEN THE Timeline_Builder SHALL emit a `progress` Tagged_Moment with `confidence` 0.0 covering that interval.
12. IF persisting `timeline.json` to the Session_Store or registering the Timeline with the VideoDB Timeline API fails, THEN THE Timeline_Builder SHALL not advertise the Timeline as available and SHALL surface an error indicating which step failed.

### Requirement 4: Generate a PR Video

**User Story:** As a developer, I want to generate a short narrated PR video from a captured session, so that reviewers can see the work in motion without watching the full recording.

#### Acceptance Criteria

1. WHEN the user runs `trace generate` with a session identifier and a target PR URL, THE PR_Video_Generator SHALL select clips from the identified Capture_Session totaling between 30 and 90 seconds of video duration, prioritizing clips associated with `progress` Tagged_Moments whose files appear in the target PR diff.
2. WHILE the cumulative duration of `progress` Tagged_Moment clips associated with files in the target PR diff exceeds 90 seconds, THE PR_Video_Generator SHALL select clips in descending order of Tagged_Moment timestamp until the 90-second limit is reached, including at least one clip per such file when possible within the limit.
3. THE PR_Video_Generator SHALL produce a narration script derived from the selected clips' transcripts and Anthropic-extracted intent summaries, with a maximum length of 1500 characters.
4. THE PR_Video_Generator SHALL synthesize the narration audio using OpenAI TTS and SHALL mix the narration with the selected clip audio at a narration-to-clip volume ratio of 1.0 to 0.3.
5. THE PR_Video_Generator SHALL render the final PR_Video as an MP4 file at 1920x1080 resolution and 30 frames per second.
6. WHEN the PR_Video has been rendered, THE Trace_CLI SHALL upload the PR_Video to VideoDB and SHALL post a comment to the target GitHub PR containing the playback URL within 60 seconds of render completion.
7. IF the target PR URL does not match the GitHub PR URL format (host github.com with path of the form `/owner/repo/pull/number`), THEN THE Trace_CLI SHALL exit with a non-zero status code and SHALL print an error message to standard error identifying the invalid URL value and the expected format.
8. IF the provided session identifier does not correspond to an existing Capture_Session in the Session_Store, THEN THE Trace_CLI SHALL exit with a non-zero status code and SHALL print an error message to standard error identifying the missing session identifier.
9. IF the identified Capture_Session contains no clips with at least 30 seconds of total available duration, THEN THE Trace_CLI SHALL exit with a non-zero status code and SHALL print an error message to standard error indicating insufficient session content for PR video generation.
10. IF the GitHub API call to post the PR comment returns an authentication error, THEN THE Trace_CLI SHALL exit with a non-zero status code, SHALL print the error message to standard error, and SHALL preserve the rendered PR_Video at the Session_Store path.
11. IF the VideoDB upload fails or the OpenAI TTS synthesis fails, THEN THE Trace_CLI SHALL exit with a non-zero status code, SHALL print an error message to standard error identifying the failed external service, and SHALL preserve the rendered PR_Video and narration script at the Session_Store path.

### Requirement 5: Decision Replay for a Code Block

**User Story:** As a reviewer, I want to click a code block and see its evolution during the session, so that I understand how the code reached its current form.

#### Acceptance Criteria

1. WHEN the user requests Decision_Replay with a file path and a line range specified by a start line number and an end line number (both integers greater than or equal to 1, with start line less than or equal to end line), THE Trace_CLI SHALL return, within 10 seconds, the ordered list of Capture_Session intervals during which any line within the specified range was inserted, modified, or deleted.
2. THE Decision_Replay SHALL include, for each returned interval, the `start_seconds` as a non-negative number, the `end_seconds` as a number strictly greater than `start_seconds`, a textual diff showing the changes applied to lines within the specified range during the interval, and a VideoDB clip URL that resolves to the recorded session segment bounded by `start_seconds` and `end_seconds`.
3. IF no Capture_Session interval is found for the requested file path and line range, THEN THE Trace_CLI SHALL return an empty list and a message indicating that no edit history was found for the specified file path and line range.
4. THE Decision_Replay intervals SHALL be ordered by ascending `start_seconds`, with ties broken by ascending `end_seconds`.
5. IF the requested file path is not present in any recorded Capture_Session, THEN THE Trace_CLI SHALL return an error message indicating that the specified file path was not found and SHALL NOT return any intervals.
6. IF the requested line range is invalid (start line less than 1, end line less than 1, start line greater than end line, or either value not an integer), THEN THE Trace_CLI SHALL return an error message indicating that the line range is invalid and SHALL NOT return any intervals.

### Requirement 6: Reviewer Q&A from Session Memory

**User Story:** As a reviewer, I want to ask questions about a PR by mentioning @trace, so that I get answers grounded in the actual session recording.

#### Acceptance Criteria

1. WHEN a GitHub PR comment containing the literal token `@trace` is received by the Trace_CLI webhook, THE Reviewer_QA SHALL extract up to 1000 characters of question text following the first `@trace` token in the comment, with leading and trailing whitespace trimmed.
2. WHEN the Reviewer_QA has extracted a non-empty question text, THE Reviewer_QA SHALL execute a semantic search against the indexed Capture_Session using the VideoDB semantic search API with the extracted question text as the query, with a maximum execution time of 30 seconds.
3. WHEN the Reviewer_QA has received semantic search results, THE Reviewer_QA SHALL post a single reply comment on the same PR thread containing a text answer of at most 500 characters and up to 3 VideoDB clip URLs ordered by descending search relevance score, including the case where zero clips meet the relevance threshold.
4. IF the semantic search returns no results with a relevance score of at least 0.3, THEN THE Reviewer_QA SHALL post a reply comment containing a text answer of at most 500 characters with zero attached clip URLs and stating that no matching session content was found.
5. IF the GitHub PR referenced by the comment has no associated Capture_Session in the Session_Store, THEN THE Reviewer_QA SHALL post a reply comment of at most 500 characters stating that no session is linked to the PR and SHALL NOT execute a semantic search.
6. IF the question text extracted after the `@trace` token is empty after whitespace trimming, THEN THE Reviewer_QA SHALL post a reply comment of at most 500 characters indicating that a question must follow the `@trace` token and SHALL NOT execute a semantic search.
7. IF the VideoDB semantic search API does not return a response within 30 seconds or returns an error response, THEN THE Reviewer_QA SHALL post a reply comment of at most 500 characters indicating that the session content could not be queried and SHALL NOT attach any clip URLs.

### Requirement 7: Human vs Agent Contribution Map

**User Story:** As a reviewer, I want to see which lines of the PR were written by a human versus an AI agent, so that I can focus my review accordingly.

#### Acceptance Criteria

1. WHEN the PR_Video_Generator processes a Capture_Session for a target GitHub PR, THE Trace_CLI SHALL produce a Contribution_Map that labels every changed line in the PR diff as exactly one of `human`, `agent`, or `mixed`, covering 100% of added and modified lines in the diff.
2. WHEN a changed line in the PR diff has Capture_Session evidence showing it was inserted by a paste action originating from an AI assistant window or by an editor AI completion event, THE Trace_CLI SHALL classify the line as `agent`.
3. WHEN a changed line in the PR diff has Capture_Session evidence showing it was produced exclusively by individual character keystroke events in the editor with no AI completion or AI-sourced paste events, THE Trace_CLI SHALL classify the line as `human`.
4. WHEN a changed line in the PR diff has Capture_Session evidence showing at least one `human` keystroke edit and at least one `agent` insertion event affecting that line within the same Capture_Session, THE Trace_CLI SHALL classify the line as `mixed`.
5. IF a changed line in the PR diff has no matching Capture_Session evidence or the evidence is insufficient to determine a classification, THEN THE Trace_CLI SHALL label the line as `unknown` in the Contribution_Map and include it in the per-file summary as a separate count.
6. WHEN the Contribution_Map is generated, THE Trace_CLI SHALL post a single comment to the target GitHub PR containing a per-file summary that lists, for each changed file, the integer count of `human`, `agent`, `mixed`, and `unknown` lines.
7. IF posting the Contribution_Map comment to the target GitHub PR fails, THEN THE Trace_CLI SHALL retry the post up to 3 times with at least 2 seconds between attempts and, if all attempts fail, exit with a non-zero status and emit an error message indicating the PR comment post failure.

### Requirement 8: Reviewer Focus Mode

**User Story:** As a reviewer, I want a compressed view of the PR limited to the key review areas, so that I can review large changes efficiently.

#### Acceptance Criteria

1. WHEN the user runs `trace generate` with the `--focus` flag, THE Trace_CLI SHALL produce a Focus_Mode artifact for the target PR in which each entry contains the file path, one or more line ranges (each expressed as a start_line and end_line that are both 1-indexed and inclusive), and the inclusion reason.
2. WHEN producing the Focus_Mode artifact, THE Trace_CLI SHALL include every file path referenced by at least one `stuck` Tagged_Moment in the Capture_Session, with the inclusion reason recorded as "stuck Tagged_Moment" and the line ranges taken from those Tagged_Moments, regardless of whether the file has zero changed lines in the target PR diff.
3. WHEN producing the Focus_Mode artifact, THE Trace_CLI SHALL include every file in the target PR diff whose changed line count is greater than or equal to 50, with the inclusion reason recorded as "large change" and the line ranges covering the changed lines reported by the diff.
4. WHEN the Focus_Mode artifact has been produced and contains at least one file, THE Trace_CLI SHALL post a single comment to the target GitHub PR that lists each included file, its line ranges, and its inclusion reason.
5. IF the Focus_Mode artifact contains zero files, THEN THE Trace_CLI SHALL post a single comment to the target GitHub PR indicating that no files met the focus criteria and SHALL exit with a success status.
6. IF posting the Focus_Mode comment to the target GitHub PR fails, THEN THE Trace_CLI SHALL retain the Focus_Mode artifact locally, emit an error message indicating that the comment could not be posted, and exit with a non-zero status.

### Requirement 9: Context-Aware PR Description

**User Story:** As a developer, I want Trace to write a PR description that explains why the change was made, so that reviewers have context beyond the diff.

#### Acceptance Criteria

1. WHEN the user runs `trace generate`, THE PR_Description_Generator SHALL produce a PR description containing a `What changed` section and a `Why` section, with the `What changed` section preceding the `Why` section.
2. THE PR_Description_Generator SHALL populate the `What changed` section with a bullet list summarizing the file-level changes in the PR diff, with one bullet per changed file and a maximum of 50 bullets; if the PR diff contains more than 50 changed files, THE PR_Description_Generator SHALL include the first 50 bullets followed by a single bullet indicating the count of additional files omitted.
3. WHEN the Capture_Session transcript and screen activity contain at least one entry, THE PR_Description_Generator SHALL populate the `Why` section using Anthropic-extracted intent summaries derived from the Capture_Session transcript and screen activity.
4. IF the Capture_Session transcript and screen activity are both empty, THEN THE PR_Description_Generator SHALL populate the `Why` section with a placeholder statement indicating that no capture data was available.
5. IF the Anthropic intent extraction fails or returns no content, THEN THE PR_Description_Generator SHALL populate the `Why` section with a placeholder statement indicating that intent extraction was unavailable, and THE Trace_CLI SHALL surface an error indication to the user identifying the failed extraction step while still producing the PR description.
6. WHERE the PR_Video exists for the Capture_Session, THE PR_Description_Generator SHALL include a link to the PR_Video in the PR description.
7. WHERE the Contribution_Map comment exists for the target GitHub PR, THE PR_Description_Generator SHALL include a link to the Contribution_Map comment in the PR description.
8. WHEN the target GitHub PR has a non-empty existing description, THE Trace_CLI SHALL append the generated description below the existing description, separated by a blank line, without modifying or removing any characters of the existing description.
9. WHEN the target GitHub PR has an empty existing description, THE Trace_CLI SHALL append the generated description below the empty existing description, producing a final description that begins with the empty existing description content followed by the generated description.
10. IF the update of the GitHub PR description fails due to network or authorization errors, THEN THE Trace_CLI SHALL preserve the existing PR description unchanged and surface an error indication to the user identifying the failure cause category.

### Requirement 10: Session Store Layout and Persistence

**User Story:** As a developer, I want session data stored locally in a predictable layout, so that I can inspect and back up sessions.

#### Acceptance Criteria

1. THE Trace_CLI SHALL store each Capture_Session under the absolute directory path `~/.trace/sessions/{session_id}/` in the local file system, where `{session_id}` is a unique identifier between 8 and 64 characters using only lowercase alphanumeric characters and hyphens.
2. WHEN a Capture_Session starts, THE Trace_CLI SHALL create a `metadata.json` file in the session directory containing the session identifier, `started_at` (ISO 8601 UTC timestamp), `status` set to `active`, `capture_mode`, and `mic_status` fields.
3. WHEN a Capture_Session stops, THE Trace_CLI SHALL update `metadata.json` to set `stopped_at` (ISO 8601 UTC timestamp) and update `status` to `completed` or `failed`, preserving all previously written fields.
4. THE Trace_CLI SHALL write the screen recording file as `screen.mp4` and the microphone recording file as `audio.wav` in the session directory regardless of whether the Capture_Session uses VideoDB RTStream capture or Fallback_Capture.
5. THE Trace_CLI SHALL write the transcript as `transcript.json` and the timeline as `timeline.json` in the session directory.
6. IF the write of `transcript.json` succeeds and the write of `timeline.json` fails, OR the write of `timeline.json` succeeds and the write of `transcript.json` fails, THEN THE Trace_CLI SHALL retain the successfully written file, SHALL NOT remove the successfully written file, and SHALL emit an error message identifying which file failed to write.
7. WHEN a session directory write fails because the path does not exist, THE Trace_CLI SHALL create the missing parent directories with owner read/write/execute permissions and SHALL retry the write exactly once within 5 seconds.
8. IF a session file write fails after the single retry described in criterion 7, OR fails for any reason other than a missing path (such as insufficient disk space or permission denied), THEN THE Trace_CLI SHALL emit an error message identifying the failed file and the failure cause category, SHALL retain any partially written or successfully written files in the session directory without rollback, and SHALL set `status` in `metadata.json` to `failed`.

### Requirement 11: Configuration and Credentials

**User Story:** As a developer, I want to configure API credentials for VideoDB, OpenAI, Anthropic, and GitHub, so that Trace can call the required services.

#### Acceptance Criteria

1. THE Trace_CLI SHALL read API credentials from the environment variables `VIDEODB_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GITHUB_TOKEN`, and SHALL treat any variable that is unset, empty, or contains only whitespace characters as missing.
2. IF a Trace_CLI command requires one or more services and one or more of the corresponding required environment variables are missing, THEN THE Trace_CLI SHALL check all required environment variables for the command, SHALL print to standard error a message listing the names of every missing environment variable, and SHALL exit with status code 2 without invoking any external service.
3. THE Trace_CLI SHALL redact every API key value in all output written to standard output, standard error, and log files by replacing all characters of the key with the character `*` except the last 4 characters, AND WHERE an API key value contains fewer than 8 characters, THE Trace_CLI SHALL replace the entire value with 8 `*` characters.
