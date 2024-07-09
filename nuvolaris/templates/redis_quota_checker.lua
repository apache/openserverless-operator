-- Define the key prefix to search for
local prefix = ARGV[1]
local cursor = 0
local total_memory = 0

repeat
    -- Use SCAN to get keys that match the prefix
    local result = redis.call('SCAN', cursor, 'MATCH', prefix .. '*')
    cursor = tonumber(result[1])
    local keys = result[2]

    for _, key in ipairs(keys) do
        -- Get memory usage of each key and add it to the total
        local memory_usage = redis.call('MEMORY', 'USAGE', key)
        if memory_usage then
            total_memory = total_memory + memory_usage
        end
    end
until cursor == 0

return total_memory