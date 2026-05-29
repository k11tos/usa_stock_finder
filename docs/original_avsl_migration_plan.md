# Original AVSL Migration Plan

## Purpose

Original AVSL should be added and evaluated in monitoring mode before it is allowed to drive trading sell decisions. The goal of the monitoring period is to compare original AVSL behavior against the existing legacy AVSL without changing the live sell path prematurely.

During this phase:

- Keep legacy AVSL as the sell-decision source of record.
- Produce original AVSL outputs side by side with legacy AVSL outputs.
- Review divergences until there is enough evidence that original AVSL is safe, stable, and understandable.
- Avoid switching sell logic from legacy AVSL to original AVSL based on a short sample, a single favorable example, or isolated backtest evidence.

## Metrics to Monitor

Track the following metrics for each daily monitoring run and summarize them over time:

1. **`LEGACY_ONLY_SELL` count**
   - Number of symbols where legacy AVSL would sell but original AVSL would not.
   - Review whether original AVSL is missing risk-reduction exits that legacy AVSL handled well.

2. **`ORIGINAL_ONLY_SELL` count**
   - Number of symbols where original AVSL would sell but legacy AVSL would not.
   - Review whether original AVSL is introducing premature exits or excessive churn.

3. **Symbols where original AVSL is much tighter**
   - Identify symbols where the original AVSL stop is materially closer to price than the legacy AVSL stop.
   - Inspect whether tightness is justified by volatility, trend structure, liquidity, and recent price action.

4. **Symbols where original AVSL is much looser**
   - Identify symbols where the original AVSL stop is materially farther from price than the legacy AVSL stop.
   - Inspect whether looseness creates unacceptable drawdown risk or delays exits after breakdowns.

5. **Realized behavior after the signal date**
   - For each divergence, review what happened in the following sessions.
   - Track whether the sell/no-sell decision would have improved or worsened outcomes after the signal date.
   - Include gap-down, rebound, sideways, and continued-trend examples.

6. **False positive examples**
   - Record cases where original AVSL would have sold but the position quickly recovered or continued upward.
   - Pay special attention to thin, low-volume, or noisy stocks where one bad print can trigger a misleading stop.

7. **False negative examples**
   - Record cases where original AVSL did not sell but price continued lower or risk increased materially.
   - Pay special attention to cases where legacy AVSL exited earlier and avoided meaningful downside.

## Minimum Observation Period

Monitor original AVSL for at least several weeks of daily runs before using it for trading sell decisions. The exact observation period is a policy choice, not a hard-coded rule, and should be set based on operational risk tolerance, market conditions, sample size, and review capacity.

Do not approve a switch only because the first few days look acceptable. The monitoring sample should include enough normal and adverse market behavior to expose potential whipsaw, liquidity, stale-data, and volatility-regime issues.

## Switch Criteria

Before original AVSL is connected to sell decisions, confirm that all of the following are true:

- Original AVSL behavior is stable across daily monitoring runs.
- There is no frequent unexplained whipsaw in `ORIGINAL_ONLY_SELL` cases.
- There are no obvious data-quality artifacts driving stop placement or sell signals.
- There are no repeated false sells in thin, low-volume, or otherwise noisy stocks.
- Divergences between legacy AVSL and original AVSL are explainable after inspection.
- Sample charts make the behavior understandable to reviewers, including both tighter-stop and looser-stop examples.
- False positive and false negative examples have been reviewed and accepted as within policy tolerance.
- The team has explicitly approved the switch from monitoring-only output to trading sell decisions.

## Rollback Plan

Keep legacy AVSL available until original AVSL has completed the monitoring period and has been approved for production sell decisions.

Rollback expectations:

- Maintain an environment flag that can route sell decisions back to legacy AVSL if original AVSL behaves unexpectedly.
- Preserve output inspection paths so reviewers can compare legacy AVSL and original AVSL after a rollback.
- Continue recording divergence output during and immediately after the switch so regressions are visible.
- If unexplained sells, data-quality artifacts, or low-volume whipsaw appear after the switch, immediately restore legacy AVSL as the sell-decision source while the issue is investigated.

## Final Cleanup Plan

After the monitoring period is complete and original AVSL has been approved:

1. Connect original AVSL to sell decisions through the agreed production flag or configuration path.
2. Continue short-term post-switch monitoring of divergence output and realized behavior.
3. Once original AVSL has proven reliable in production, remove or archive legacy AVSL code and documentation.
4. Keep enough historical comparison output to explain the migration decision and support future audits.
