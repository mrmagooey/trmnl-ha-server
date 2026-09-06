"""Test-suite-wide fixtures and environment pinning.

Golden image comparisons are byte-exact, so anything that varies between
machines has to be pinned here rather than baked into a reference image.
"""

import os
import time

# Graph axis labels are rendered with datetime.astimezone(), which converts to
# the server's LOCAL time — correct behaviour for a home dashboard, since the
# device should show local time rather than UTC. That makes the rendered labels
# depend on the host's clock configuration, so the golden images would only
# match on a machine sharing the developer's timezone. Pin UTC for tests so the
# references are reproducible; production behaviour is deliberately unchanged.
os.environ["TZ"] = "UTC"
time.tzset()
