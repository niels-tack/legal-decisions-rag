# ChatGPT Custom GPT setup

This guide walks the **maintainer** (technical, solo) through wiring the hosted search API into a ChatGPT Custom GPT Action, as the second of the two platforms named in the functional requirements alongside Microsoft Copilot Studio (see `docs/copilot-studio-setup.md`). The end result is the same: end users open a shared Custom GPT link and ask plain-language questions about Belgian Constitutional Court rulings, with zero installs and no API key of their own.

> UI note: OpenAI's GPT Editor / Actions UI changes fairly often. The steps below describe the screen structure and terminology as of the time this guide was written. If a label has moved, look for the nearest equivalent rather than assuming the integration itself has changed.

## Prerequisites

- **The deployed query service URL** - from `terraform output query_service_url` (or equivalent), e.g. `https://<container-id>.fnc.fr-par.scw.cloud`.
- **The shared API key** - the `SHARED_API_KEY` value.
- **`docs/openapi.json`** from this repo, with the placeholder server URL replaced by the real deployed URL.
- A ChatGPT account with access to GPT creation (a Plus, Team, or Enterprise plan - Custom GPT creation is not available on the free tier).

## Step 1: Prepare the OpenAPI spec

Same as the Copilot Studio flow: open `docs/openapi.json`, replace the placeholder `servers[0].url` with the real container URL, and keep the edited copy handy to paste in during Action setup. Keep the placeholder in the committed file in source control.

## Step 2: Create (or edit) the Custom GPT

1. In ChatGPT, go to **Explore GPTs** → **+ Create**, or open an existing GPT and select **Edit**.
2. Use the **Configure** tab (skip the conversational "GPT Builder" chat if you prefer to set fields directly).
3. Set a clear **Name** and **Description**, e.g. name "Grondwettelijk Hof Rechtspraak" / description "Answers questions about Belgian Constitutional Court rulings with citations to the official case law."

## Step 3: Write the GPT's instructions

In the **Instructions** field on the **Configure** tab, enter:

```
You are an assistant that answers questions about rulings of the Belgian
Constitutional Court (Grondwettelijk Hof), using only the results returned
by the "searchConstitutionalCourtRulings" action. The rulings you can search
are currently Dutch-language only.

Whenever a user asks about Belgian Constitutional Court case law - a
specific case, a legal topic, an article of law, a date range, or anything
that sounds like it needs a citation to a real ruling - call the
searchConstitutionalCourtRulings action with their question (or the exact
citation they gave you) as the "q" parameter before answering. Do not answer
from your own general knowledge about Belgian constitutional law without
first calling the action.

When you answer:
- Base your answer only on the excerpts returned by the action. If the
  action returns no relevant results, say so plainly instead of guessing
  or inventing a ruling.
- For every ruling you reference, you MUST cite it using all three of: the
  ECLI (ecli), the case number (case_number), and the ruling date
  (ruling_date). Never cite a ruling using only one of these.
- Always include a link to the source_pdf_url for each ruling you cite, so
  the user can open and verify the original official PDF.
- Do not present your answer as legal advice. Make clear you are
  summarizing official case law, and that the user should consult the
  original ruling (via the linked PDF) or a legal professional for advice
  on their specific situation.
- If results are in Dutch and the user asked in another language, you may
  translate the excerpt for the user, but keep the ECLI, case number, and
  official citation details untranslated and exact.
```

Optionally add a few **Conversation starters** such as "What has the Court decided about environmental permits?" to help users discover what the GPT is for.

## Step 4: Add the Action from the OpenAPI spec

1. Still on the **Configure** tab, scroll to **Actions** and select **Create new action**.
2. In the action editor, select **Import from URL** if you're hosting the edited spec somewhere reachable, or paste the full contents of the edited `docs/openapi.json` directly into the schema text box (either works; pasting avoids needing to host the file anywhere).
3. ChatGPT will parse the schema and list the two operations: `searchConstitutionalCourtRulings` (`GET /search`) and `getServiceHealth` (`GET /health`). Both are imported as part of the same Action; only `searchConstitutionalCourtRulings` is expected to be called in normal use, since `getServiceHealth` is described in the spec as an infrastructure-only endpoint.
4. Check the **Available actions** privacy setting shows `x-openai-isConsequential: false` was picked up (this is set in the spec for both operations) - it tells ChatGPT these are safe, non-mutating GET calls, so it won't insert an extra "do you want me to do this?" confirmation before every search.

## Step 5: Configure the shared API key as a fixed Action-level credential

This is the step that keeps the key completely invisible to end users.

1. In the Action editor, select **Authentication** (near the schema import area).
2. Choose **API Key** as the auth type.
3. Set:
   - **API Key**: paste the shared key from your prerequisites.
   - **Auth Type**: **Custom**.
   - **Custom Header Name**: `X-API-Key`.
4. Save. This credential is stored against the GPT itself (by the maintainer, while editing/configuring it), not requested from or visible to anyone chatting with the published GPT afterward - end users never see an auth prompt for this Action.
5. If you later need to rotate the key, update it here (Configure → Actions → Authentication) and republish (Step 7) - there is no other place in the ChatGPT UI where this value lives.

## Step 6: Test before publishing

1. Use the **Preview** pane on the right side of the GPT editor to chat with the GPT as it's currently configured (this works even before publishing).
2. Ask a sample question, e.g.:
   - "What has the Constitutional Court decided about environmental permits?"
   - "Wat besliste het Grondwettelijk Hof in arrest 1/2025?"
3. When the GPT calls the action, the Preview pane shows a "Talking to <action host>" indicator you can expand to see the request/response - confirm it hit `/search` on your real container URL and got a `200` with results, not a `401` (bad key) or a call to the placeholder host (spec not updated).
4. Confirm the final answer cites the ECLI, case number, and ruling date, and links `source_pdf_url`.
5. Ask an off-topic or no-match question and confirm the GPT reports no relevant ruling rather than fabricating one.

## Step 7: Publish and share

1. Select **Save** (or **Update** for an existing GPT), top right of the editor.
2. Choose a **sharing scope**:
   - **Only me**: for your own testing only.
   - **Anyone with a link**: the typical choice for this project - generates a shareable URL you can hand to end users (or link from a website/README) with no ChatGPT Plus requirement beyond having any ChatGPT account able to open shared GPT links per OpenAI's current policy.
   - **Public / GPT Store**: lists the GPT publicly in the GPT Store, for maximum discoverability if that fits the project's goals.
3. Share the resulting link. Opening it and asking a question is the entire end-user experience - no install, no key, no configuration on their end.
4. As with Copilot Studio, publishing here is a manual step - re-publish (Save/Update) whenever the instructions or the Action's schema/auth changes.

## Keeping the Action in sync with redeployments

If the Scaleway container URL changes (e.g. Terraform recreates rather than updates the container):

1. Open the GPT's **Configure** → **Actions**, edit the existing action's schema, and update the host to the new URL (re-paste the updated `docs/openapi.json`, or edit the `servers[0].url` value directly in the schema editor).
2. Re-test (Step 6) and re-save/publish (Step 7).

The shared API key does not need to change on redeploy unless `SHARED_API_KEY` itself is rotated.
