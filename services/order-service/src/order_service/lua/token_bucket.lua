-- Token bucket for 1 client, shared by every order-service copy.
-- KEYS[1]: ratelimit:{client}
-- ARGV: capacity (max burst), refill_per_second
-- Returns: {1, 0} if allowed, {0, retry_after_ms} if not.
local time = redis.call('TIME')
local now_ms = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])

local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1]) or capacity
local last_ms = tonumber(state[2]) or now_ms
tokens = math.min(capacity, tokens + (now_ms - last_ms) * rate / 1000)

local allowed, retry_ms = 0, 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_ms = math.ceil((1 - tokens) * 1000 / rate)
end

redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', now_ms)
redis.call('PEXPIRE', KEYS[1], 60000)
return {allowed, retry_ms}
