# Where this goes

Clearwake (PayPal) and Relayloom (Meta) are two entries built on the same engine, verdock-core. The hackathons prove it on two real platforms. Each line below is tagged **built** or **planned**. Nothing planned is presented as built.

## Today, on PayPal
* **Built.** Limits live outside the model, in a policy file whose hash is in every receipt. A prompt, a buyer message or a model reply cannot change them.
* **Built.** Explicit, recorded approvals above a threshold: who approved, the exact action and amount, the limit and the time. The requester cannot approve their own request.
* **Built.** Swarm invariants: one agent per case, refunds per capture and per customer per day capped across parallel agents, and one stable PayPal request id per action.
* **Built.** Every money movement is checked against PayPal's own record by a separate read. A lost response stays UNKNOWN until reconciled and is never retried blindly.
* **Built.** Signed, hash chained receipts on the buyer and merchant side that anyone can verify with the network off.
* **Built.** Evidence for PayPal disputes, gathered only from records, with deadline escalation to a person.

## Next
* **Built (31 October).** Agents, policy, checks, receipts and the local model run on a network isolated Docker network; one verdock-core egress gateway reaches only the PayPal sandbox and receipts every request; a network cut holds money actions as "held, offline" (case m). **Planned:** the same boundary for every daily operation, not only the demo cases.
* **Planned.** Private mode on local open weights models by default. A local model already runs the agents' proposals as an option.
* **Planned.** Shared context for teams of people and agents working on one goal. Relayloom is the start of this.
* **Planned.** Continuous operations: agents run every day and every outcome is checked.
* **Planned.** The same receipts accepted by payment platforms as proof of what an agent did and under which mandate.

## The PayPal story
PayPal merchants get disputes today and lose many of them because evidence is slow to gather. Clearwake answers each one inside the merchant's limits, with proof. As more purchases come from AI agents, merchants will also need agents on their side that settle disputes and refunds within limits and with proof of the buyer's mandate. Clearwake does that on PayPal now.
