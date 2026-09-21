# Polymarket Paper Trader

Automated paper trading only. No wallet and no real orders.

- $50 virtual bankroll
- 8 percentage-point minimum edge
- Half Kelly
- 6% maximum bankroll risk per trade
- 5 open positions maximum
- 40% peak drawdown stop
- Public Polymarket market data
- OpenRouter free model router
- Runs every 30 minutes

The 30-minute schedule keeps the bot within OpenRouter's current free 50-request/day limit. This free setup does not give the model live X access, so it is an experiment rather than a reproduction of the viral Grok+X strategy.
