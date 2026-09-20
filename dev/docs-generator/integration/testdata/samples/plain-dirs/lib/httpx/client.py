# doc() httpx-retry: Retry policy
#   section: Behaviour
#   order: 10
#   Retries are capped at three attempts with jitter. The cap exists because the upstream
#   budget is shared, not because three is special.
#
# diagram() httpx-flow: Call path
#   section: Behaviour
#   order: 20
#   flowchart TD
#     call[caller] --> rl{rate limited?}
#     rl -->|no| up[upstream]
#     rl -->|yes| backoff[backoff + jitter]
#     backoff --> up

def get(url):
    return url
