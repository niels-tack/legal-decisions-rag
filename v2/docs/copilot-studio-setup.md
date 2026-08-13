# Microsoft Copilot Studio setup

This guide walks the **maintainer** (technical, solo) through wiring the hosted search API into a Microsoft Copilot Studio agent so that **end users** (non-technical) can ask plain-language questions about Belgian Constitutional Court rulings inside Microsoft Copilot with zero installs and zero API keys of their own.

You do this setup once per agent. End users never see any of these steps, never see the shared API key, and never interact with anything in this document directly.

For the equivalent ChatGPT flow, see `docs/custom-gpt-setup.md`.

> UI note: Copilot Studio's screens change fairly often. The steps below describe the menu structure and terminology as of the time this guide was written. If a label has moved, look for the nearest equivalent (e.g. "Actions" and "Tools" are sometimes used interchangeably in the UI) rather than assuming the integration itself has changed.

## Prerequisites

Before starting, have the following ready:

- **The deployed query service URL** - the Scaleway Serverless Container endpoint, from the Terraform output (e.g. run `terraform output query_service_url` in the infrastructure directory). It looks like `https://<container-id>.fnc.fr-par.scw.cloud`.
- **The shared API key** - the value stored in the `SHARED_API_KEY` secret (GitHub Secrets / Terraform-managed secret / Scaleway Secret Manager, depending on how it was provisioned). This is the value the query service compares against the `X-API-Key` header.
- **`docs/openapi.json`** from this repo, with the placeholder server URL replaced by the real deployed URL (see step 1).
- A Microsoft 365 / Power Platform account with permission to create Copilot Studio agents (a work or school account with a Copilot Studio license or trial).

## Step 1: Prepare the OpenAPI spec

1. Open `docs/openapi.json` from this repo.
2. Replace the placeholder `servers[0].url` value (`https://REPLACE-WITH-YOUR-DEPLOYED-CONTAINER-URL.fnc.fr-par.scw.cloud`) with the real container URL from the Terraform output.
3. Save this edited copy somewhere you can upload it from (you do not need to commit the edited copy back to the repo - keep the placeholder in source control so it's obvious a real URL must be substituted per environment).

## Step 2: Create (or open) a Copilot Studio agent

1. Go to [Microsoft Copilot Studio](https://copilotstudio.microsoft.com) and sign in.
2. To create a new agent: select **Create** (or **+ New agent**) from the home page, then choose **Skip to configure** (or the equivalent "start from blank" option) rather than a templated agent, so you control the instructions from scratch.
3. Give the agent a clear name and description, e.g. name "Grondwettelijk Hof Rechtspraak" / description "Answers questions about Belgian Constitutional Court rulings with citations to the official case law."
4. To update an existing agent instead, open it from the **Agents** list in Copilot Studio and go directly to step 3 below.

## Step 3: Add the search action from the OpenAPI spec

1. In the agent's authoring canvas, go to the **Tools** (or **Actions**) tab.
2. Select **Add a tool** → **New tool** → **Custom connector** (this creates a Power Platform custom connector backing the action).
3. In the custom connector creation dialog, choose **Import an OpenAPI file** and upload the edited `docs/openapi.json` from Step 1.
4. Confirm the connector's basic info (name, description, host) is populated correctly from the spec - the host should match the real container URL, not the placeholder.
5. On the **Security** page of the connector wizard, Power Platform should detect the `ApiKeyAuth` security scheme from the spec and offer **API Key** as the authentication type, with the key delivered via a header named `X-API-Key`. Confirm this is selected (see Step 4 for where the actual key value is entered).
6. On the **Definition** page, confirm both operations were imported: `searchConstitutionalCourtRulings` (`GET /search`) and `getServiceHealth` (`GET /health`). You can leave `getServiceHealth` in the connector definition, but you do not need to expose it as an agent-callable tool - only `searchConstitutionalCourtRulings` should be enabled for the agent to call (see Step 3.8).
7. Select **Create connector**, then **Test** the connector: create a new connection, and when prompted for the API key, paste the shared key from your prerequisites, then run a sample call against `/search` with a `q` value to confirm you get a `200` response with results.
8. Back in the agent's **Tools** tab, add the newly created connector as a tool on the agent, and if the UI lets you pick individual operations per tool, restrict it to `searchConstitutionalCourtRulings` only (excluding `getServiceHealth`, which is an infrastructure-only endpoint not meant for the agent to call while answering user questions).

## Step 4: Configure the shared API key as a fixed connector-level credential

This is the step that keeps the key completely invisible to end users.

1. When you created the connection in Step 3.7 (or afterward via **Tools** → the connector → **Connections** / **Edit connection**), you were asked for the API key value as part of setting up the **connection**, not as part of the agent's conversation flow or a variable the bot asks the user for.
2. Paste the shared key exactly as stored in your secret (GitHub Secrets / Scaleway Secret Manager) into that connection's API key field. This value is stored by Power Platform against the **connection**, which is owned by the maintainer's environment/account - it is never part of the bot's dialog, never shown in a message to the user, and never requested from the user at runtime.
3. If Copilot Studio/Power Platform asks whether the connection should use "the maker's connection for everyone" (as opposed to requiring each user to sign in individually), choose the maker/shared-connection option. This is what makes the integration zero-setup for end users - they inherit the maintainer's pre-configured connection rather than being prompted to authenticate themselves.
4. Double check: open the agent in **Test** mode (see Step 6) and confirm you are never prompted to sign in or supply a key as an end user during a test chat. If you are prompted, the connection is misconfigured as per-user rather than shared/fixed - revisit the connection's sharing settings.

## Step 5: Write the agent's instructions (system prompt)

Open the agent's **Instructions** (sometimes labeled **General** → **Instructions**, or shown as the top-level system prompt field) and set it to something like the following. Adjust wording/tone to match your agent's persona, but keep the citation requirement intact:

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
  ECLI (ecli), the arrest number (arrest_number), and the ruling date
  (ruling_date). Never cite a ruling using only one of these.
- Always include a link to the source_pdf_url for each ruling you cite, so
  the user can open and verify the original official PDF.
- Do not present your answer as legal advice. Make clear you are
  summarizing official case law, and that the user should consult the
  original ruling (via the linked PDF) or a legal professional for advice
  on their specific situation.
- If results are in Dutch and the user asked in another language, you may
  translate the excerpt for the user, but keep the ECLI, arrest number, and
  official citation details untranslated and exact.
```

## Step 6: Test the agent before publishing

1. Use the **Test** pane (usually docked on the right side of the authoring canvas) to chat with the agent as if you were an end user.
2. Ask a sample question that should trigger the action, e.g.:
   - "What has the Constitutional Court decided about environmental permits?"
   - "Wat besliste het Grondwettelijk Hof in arrest 1/2025?"
3. Confirm that:
   - The agent actually invokes `searchConstitutionalCourtRulings` (Copilot Studio's test pane typically shows a trace/activity log of tool calls - check it fired and returned a `200`).
   - The final answer includes the ECLI, arrest number, and ruling date for each cited ruling, plus a link to the source PDF.
   - Asking about a topic with no matching rulings produces an honest "no relevant ruling found" answer rather than a fabricated one.
   - No sign-in or API-key prompt appears to you as the test user (see Step 4.4).
4. If the action isn't firing, check the **Tools** tab to confirm it's enabled for this agent's topic/orchestration, and re-read the instructions from Step 5 - Copilot Studio's generative orchestration decides when to call a tool based on the tool's description and the agent instructions, so a vague description can suppress calls. The `description` fields in `docs/openapi.json` are written specifically to make Copilot Studio's model aware of when to call the action.

## Step 7: Publish and share the agent

1. Once testing looks correct, select **Publish** (top right of the authoring canvas) to publish the current draft to production.
2. Go to the **Channels** tab to make the agent available where end users actually are:
   - **Microsoft Teams**: enable the Teams channel and share the agent (or make it organization-wide, depending on your tenant's policy) so users can add it directly in Teams with no install beyond adding the bot.
   - **Custom website / demo website**: Copilot Studio provides a shareable web chat link/embed if you want a browser-based option outside Teams.
   - If your tenant has it enabled, Copilot Studio agents can also surface inside **Microsoft 365 Copilot** itself as a plugin/agent, which is the most "zero setup" path for users already using Copilot day to day.
3. Confirm the published channel(s) still exhibit the zero-key behavior from Step 4 - open the shared link/Teams app as a different account if possible and repeat a sample question.
4. Note the publish is a manual step (this project has no CI step that publishes Copilot Studio changes automatically); re-publish whenever you update the instructions or the OpenAPI spec (e.g. after redeploying the container to a new URL - see the note below).

## Keeping the connector in sync with redeployments

The container URL in `servers[0].url` is only stable as long as the underlying Scaleway Serverless Container isn't recreated. If Terraform ever recreates the container (rather than updating it in place) and the URL changes:

1. Update the custom connector's host/base URL (Tools → the connector → **Edit** → re-import or manually update the host field) to the new Terraform output value.
2. Re-test (Step 6) and re-publish (Step 7).

The shared API key itself does not need to change on redeploy unless it is rotated independently in `SHARED_API_KEY`.
