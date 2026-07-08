# Shared chunk-queue building logic for both local and remote parallel
# tournament dispatch (run_parallel.ps1, run_remote_parallel.ps1, and their
# respective supervisors: supervise_local_chunks.ps1, supervise_remote_chunks.ps1)
# -- kept in one place so the two backends can never silently diverge on
# how -ChunksPerShard/-ChunksPerHost + -ChunksPerFormat turn into an actual
# (format, chunk) work queue. Dot-source this, same convention as
# _remote_chunk_launch.ps1/_local_chunk_launch.ps1.

# "singles, doubles" -> @("singles","doubles"), trimmed, blanks dropped.
# Also used by run_tournament.ps1 to parse its own -Formats.
#
# The `,$result` (unary comma) wrap is load-bearing, not decoration: a plain
# `return @(...)` still gets unrolled by the pipeline down to a bare scalar
# at the call site whenever exactly one element flows through it (the normal
# case for every single-format per-chunk watchdog invocation) unless the
# CALLER separately re-wraps the result in @(...). `,$result` nests $result
# inside one more array layer, so the pipeline's one level of unrolling peels
# that off and hands the caller $result itself, intact, regardless of how
# the caller captures it (`$x = Get-FormatList ...` with no @() is then
# safe). Confirmed live 2026-07-08: an un-rewrapped call site in
# run_tournament.ps1 silently ran with $Format = "s"/"d" (character-indexing
# a scalar string instead of array-indexing a 1-element array) for an entire
# rerun.
function Get-FormatList([string]$Formats) {
    $result = @($Formats -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    return ,$result
}

# Generic "format=value,format=value" parser -- e.g. -ChunksPerFormat
# ("singles_uncursed=3,doubles_uncursed=1") and run_tournament.ps1's
# -SubsetPairsPath (e.g. "singles=Analysis/subset_pairs_singles.tsv,doubles=Analysis/subset_pairs_doubles.tsv")
# share this exact shape: override a per-run default for specific formats
# only, leaving every other named format alone. Kept here as one shared
# parser rather than reimplementing the same split/validate logic wherever
# a new per-format override is needed -- values are returned as raw
# strings; callers that need a different type (e.g. int) cast themselves.
#
# $FormatList (if non-empty) validates every key actually names a format in
# that list -- appropriate at the top-level launcher (run_parallel.ps1/
# run_remote_parallel.ps1), which always sees the *whole* -Formats sequence.
# Pass an empty array to skip validation -- required for
# run_tournament.ps1's per-chunk use (Resolve-SubsetPairsPathForFormat):
# once dispatch is chunked, each individual process only ever receives one
# format via its own -Formats (the chunk it was assigned), never the full
# sequence the map might span, so validating against that one-item list
# would wrongly reject every other format's legitimate entry.
function ConvertFrom-FormatKeyedOverrides([string]$Raw, [string[]]$FormatList, [string]$FieldName) {
    $result = @{}
    foreach ($pairStr in ($Raw -split "," | Where-Object { $_ -and $_.Trim() })) {
        $parts = $pairStr.Split("=", 2)
        if ($parts.Count -ne 2) { throw "Malformed $FieldName entry '$pairStr' -- expected format=value" }
        $fmtName = $parts[0].Trim()
        if ($FormatList -and -not ($FormatList -contains $fmtName)) {
            throw "$FieldName names format '$fmtName' which isn't in the format list ($($FormatList -join ', '))"
        }
        $result[$fmtName] = $parts[1].Trim()
    }
    return $result
}

# Builds the flat, priority-ordered (format-major, chunk-minor) work queue
# -- see run_remote_parallel.ps1's header for the full rationale: this flat
# FIFO ordering is what implements "finish every chunk of one format before
# any chunk of the next starts, without leaving a free shard/host idle
# waiting on some other slow one" with no explicit barrier logic.
#
# $ChunksPerFormatOverride is the "format=count,format=count" string (e.g.
# "singles_uncursed=3,doubles_uncursed=1") -- see that same header for why
# this exists (an uncursed subset can have an order of magnitude fewer
# pairs than its cursed counterpart, not worth the same chunk count). Any
# format not named there falls back to $DefaultChunkCount.
function New-ChunkQueue([string[]]$FormatList, [int]$DefaultChunkCount, [string]$ChunksPerFormatOverride) {
    $chunkCountByFormat = @{}
    foreach ($fmt in $FormatList) { $chunkCountByFormat[$fmt] = $DefaultChunkCount }
    $overrides = ConvertFrom-FormatKeyedOverrides -Raw $ChunksPerFormatOverride -FormatList $FormatList -FieldName "chunks-per-format"
    foreach ($fmtName in $overrides.Keys) { $chunkCountByFormat[$fmtName] = [int]$overrides[$fmtName] }

    # List[object], not a plain array -- see run_remote_parallel.ps1's
    # comment on the same choice (O(1) amortized front-removal via
    # RemoveAt(0)/Select-Object -Skip 1, and .ToArray() sidesteps a real
    # runtime bug coercing a List[object] straight to a JSON-serializable
    # array with @()).
    $queue = New-Object System.Collections.Generic.List[object]
    foreach ($fmt in $FormatList) {
        for ($c = 0; $c -lt $chunkCountByFormat[$fmt]; $c++) {
            $queue.Add([PSCustomObject]@{ format = $fmt; chunk = $c })
        }
    }
    return [PSCustomObject]@{ chunkCountByFormat = $chunkCountByFormat; queue = $queue }
}

# Pretty "format=count, format=count" summary for a launch-time log line.
function Get-ChunkCountSummary([string[]]$FormatList, $ChunkCountByFormat) {
    return ($FormatList | ForEach-Object { "$($_)=$($ChunkCountByFormat[$_])" }) -join ", "
}
