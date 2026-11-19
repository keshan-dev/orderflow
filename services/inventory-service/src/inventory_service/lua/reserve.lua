-- Reserve stock for 1 order, all items or nothing, as 1 step nobody can interrupt.
-- KEYS: stock:{p1}, ..., stock:{pN}, hold:{order_id}
-- ARGV: qty1, ..., qtyN, hold_json, hold_ttl_seconds
-- Returns: 1 = reserved now, 2 = this order already holds its stock, 0 = not enough stock
local n = #KEYS - 1
local hold = KEYS[#KEYS]

if redis.call('EXISTS', hold) == 1 then
  return 2
end

for i = 1, n do
  local have = tonumber(redis.call('GET', KEYS[i]) or '0')
  if have < tonumber(ARGV[i]) then
    return 0
  end
end

for i = 1, n do
  redis.call('DECRBY', KEYS[i], ARGV[i])
end
redis.call('SET', hold, ARGV[n + 1], 'EX', ARGV[n + 2])
return 1
