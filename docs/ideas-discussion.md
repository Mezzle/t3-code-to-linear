# Let Linear delegate issues to T3 Code as an agent

## Problem

Linear lets an OAuth app act as an agent. People assign an issue to it, or @mention it in a comment, and Linear opens an agent session on the issue. The app posts its progress back into that session as activities.

T3 Code can't be one of those agents today. The Linear work in progress (#19274, #19576) brings Linear issues into T3. Nothing goes the other way, so starting work from Linear still means copying the issue into a new thread by hand. A comment on #6752 asked for exactly this and got no reply.

## Proposal

Register T3 Code as a Linear agent. Delegating an issue to it starts a thread in the bound project. The thread's result then shows up on the issue.

- **Delegate or mention** starts a thread in a new worktree for the issue. The prompt comes from Linear's `promptContext` (issue, comments, team guidance), framed as untrusted data the way webhook task prompts already are.
- **A reply in the Linear session** goes to the same thread as its next message.
- **Stop in Linear** interrupts the thread.
- **When the thread settles**, T3 posts the last reply as a `response`. A pending question becomes an `elicitation`. A failed run becomes an `error` with a link to the thread.

Linear requires a 2xx within 5 seconds and a first activity within 10 seconds, or it marks the agent unresponsive. So the server would acknowledge right away and start the thread after that.

## Why in the server

Most of what this needs already exists:

- The webhook route and relay forwarding from #15085 and #22194, with HMAC verification and dedupe. Linear's `Linear-Signature` is a plain hex HMAC-SHA256 of the body, so it fits the existing check.
- The secret store for the Linear token.
- Thread launch, interrupt, and the orchestration event stream to see when a run settles.
- The project to Linear team binding from #19274.

What's new is a Linear agent webhook handler, a table mapping Linear session ids to thread ids, a listener that posts activities when a thread settles, and the OAuth install. Linear's agent features need an app login (`actor=app` with `app:assignable` and `app:mentionable`), not the personal API key #19274 uses, so the install is a separate step. The GraphQL client from #19274 could be reused for the API calls.

I looked at a separate bridge service that runs `t3 thread start/send/show`. It works, but it needs its own public URL, has no way to interrupt, and duplicates the webhook handling above.

## Smallest useful scope

One Linear workspace. Delegate and mention start a thread. Replies continue it. The final reply, questions and errors post back. No intermediate thoughts, no plan sync, no multi-workspace install.

## Questions for maintainers

1. Is this a direction you'd take, and should it wait for #19274 to land?
2. Does the relay forward any path under `/v1/hooks/<key>/`, or only scheduled task paths? That decides whether Linear can reach the server through the relay without changes to it.
3. The OAuth install needs a redirect URL. Is serving it through the relay acceptable, or would you rather start with a token the user pastes in after authorizing once?

I'm happy to build it in a fork first and share a recording before opening a PR.
