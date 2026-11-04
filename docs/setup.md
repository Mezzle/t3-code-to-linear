# Setup

This connects a Linear workspace to a T3 Code server, so people can assign or @mention a T3 agent on Linear issues.

Some steps happen in T3 (a T3 agent can do most of them for you) and some in Linear's settings, which only a workspace admin can do. Do them in this order. The T3 webhook URL has to exist before the Linear app can point at it, and Linear's signing secret only exists after the app does.

Status: all steps have run on a real workspace. A delegated issue started a work thread, which posted back to Linear. Replies and stop signals (`prompted`) haven't been tested yet.

## What you need

- A T3 Code server with T3 Connect remote access on (`t3 connect status` shows `Exposure: enabled`). Webhook URLs come from the T3 relay.
- Codex set up in T3, for the fast dispatcher model.
- `curl` and `jq` on the T3 host.
- Admin rights in the Linear workspace.
- This repo added as a T3 project. It is the *dispatch project*. Webhook runs start here, then hand the real work to a thread in the right project.

## 1. Set the dispatcher task's model (T3 UI, after step 2)

Linear marks the agent unresponsive unless it posts something within 10 seconds of a delegation, so the dispatcher needs a fast model.

A scheduled task has its own model and workspace settings, and it ignores the project's defaults. Once the task from step 2 exists, open **Settings → Scheduled tasks**, pick the task, and set the model to **Codex → GPT-6.1 Terra**, effort **Low**, **Fast** (the priority tier). Set the workspace to **Current checkout**, because a dispatcher run doesn't need its own worktree.

Measured on the first live delivery: Linear to the provider turn starting took 1.4 s (relay, T3, thread start). Everything after that is the model. Opus 5.5 took a further 9.2 s and missed the deadline at 10.6 s. In the grader (`eval/`), Terra on the priority tier had a median of 3.2 s and never went over 4.4 s.

The `schedule_task` tool can't set a task's model, so this step has to be done in the UI.

At the moment the scheduled task picker doesn't offer Fast (https://github.com/pingdotgg/t3code/pull/30729 fixes that). Until it does, pick Terra on Low with the default tier. In the grader that had a median of 5.0 s, and its slowest run was 6.3 s.

## 2. Create the webhook task (T3)

Ask a T3 agent in this project to create a scheduled task:

- trigger `{type: "webhook"}`, filter `body.type equals AgentSessionEvent`, `maxDeliveryAgeMinutes: 30`
- `bindToCurrentThread: false`, so each delivery gets its own thread
- the prompt from `docs/task-prompt.md`, with `@ROOT@` replaced by this repo's absolute path

The result includes a `webhookUrl` on `relay.t3.codes`. The token in that URL is a credential, so don't commit it or paste it anywhere public.

## 3. Create the Linear app (Linear, admin)

1. Linear → **Settings → API → OAuth applications → Create new**.
2. Name it (for example "T3"). People will see this name when they assign issues. Add an icon if you like.
3. **Callback URL**: `http://localhost:8765/callback`. Nothing needs to listen there. The install in step 5 only needs Linear to accept the redirect.
4. Turn on **Client credentials**. The `bin/linear` helper uses this grant to get 30-day app tokens without a browser.
5. Turn on **Webhooks**. Set the URL to the `webhookUrl` from step 2, and tick only **Agent session events**. Other categories would start a T3 run for every matching event.
6. Save. Copy the **client ID**, **client secret** and **webhook signing secret**.

## 4. Store the credentials (T3 host)

The easiest way is to ask the T3 agent to do it. It calls `request_secret` with `delivery: "file"` for the client ID and the client secret, then writes the file below, so the values never go into chat. To do it by hand, replace the whole `<...>` placeholder, angle brackets included. Leaving them in breaks the file.

```sh
mkdir -p ~/.config/t3-linear-agent && chmod 700 ~/.config/t3-linear-agent
cat > ~/.config/t3-linear-agent/env <<'EOF'
LINEAR_CLIENT_ID=<client id>
LINEAR_CLIENT_SECRET=<client secret>
LINEAR_SCOPE=read,write,app:assignable,app:mentionable
EOF
chmod 600 ~/.config/t3-linear-agent/env
bin/linear token >/dev/null && echo ok
```

## 5. Install the app as an agent (Linear, admin)

Open this URL in a browser while signed in to Linear as an admin, with your client ID in place:

```
https://linear.app/oauth/authorize?client_id=<client id>&redirect_uri=http%3A%2F%2Flocalhost%3A8765%2Fcallback&response_type=code&scope=read,write,app:assignable,app:mentionable&actor=app&state=install
```

`actor=app` installs it as an app user rather than acting as you. `app:assignable` and `app:mentionable` let people delegate issues to it and @mention it. Approve it. The browser then fails to load `localhost`, which is expected.

**Verify**: the app appears when you search for its name in an issue's Assign menu. Until it has been used, it doesn't show in the short list, so type the name. If it doesn't, check that `LINEAR_SCOPE` in step 4 includes `app:assignable,app:mentionable`, delete `~/.cache/t3-linear-agent/token.json`, and run `bin/linear token` again. A token issued with only `read,write` leaves the app unassignable.

## 6. Add the signing secret to the task (T3)

Ask the T3 agent to update the task's signature with the Linear signing secret, using `request_secret` so the secret never goes into chat:

- header `linear-signature`, encoding `hex`, prefix empty

An update replaces the whole `schedule` object. Send the signature, filter, `maxDeliveryAgeMinutes` and a dedupe `replayKey` of `{{headers.linear-delivery}}` together in one update. If you leave the signature out, T3 removes the stored signing secret and you have to enter it again.

`bin/linear gql '{ viewer { name app } }'` should now print the app's name with `app: true`. A client credentials token can't read `organization`, so don't use that query to test.

**Verify**: after the next delivery, the task's delivery log shows `accepted`, not `rejected_signature`.

## 7. Map Linear teams to T3 projects (T3 host)

`bin/t3-dispatch` starts each work thread in the T3 project mapped to the issue's team. Teams that aren't listed get an error in Linear instead. Find project ids with `t3 project list` or ask the T3 agent.

```sh
cat > ~/.config/t3-linear-agent/projects.json <<'EOF'
{"teams": {"CON": {"project": "<project id or path>", "baseRef": "main"}}}
EOF
```

Each work thread runs in a new worktree on a `t3/<issue id>` branch from `baseRef`. Add `"provider"` and `"model"` to a team to override that project's default model.

## 8. Test

Delegate an issue to the app. Within a few seconds Linear should show "Picked up by T3.", and a work thread should appear in the mapped project. When it finishes, its summary arrives on the issue as a response.

**Verify** on the first run: the work thread starts. If it doesn't, the dispatcher thread's reply shows the error from `bin/t3-dispatch`.

To measure timing or capture a raw payload instead, swap in a probe prompt that times the ack and writes `{{request}}` to a file. That's how the numbers in step 1 were taken.
