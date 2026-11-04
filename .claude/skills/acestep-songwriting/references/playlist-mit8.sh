#!/usr/bin/env bash
#
# Reproduces the eight-track Men I Trust-leaning playlist, exactly as shipped.
#
# Every caption, seed and parameter below was verified by md5 against the
# approved audio, so re-running this reproduces those files rather than
# something merely similar. Seeds are the part that cannot be recovered by
# ear, which is why this script exists at all.
#
# The arc: 95 -> 108 -> 114 -> 132 (peak) -> 120 -> 104 (instrumental) -> 90 -> 76.
# Track 06 is instrumental on purpose, for variety mid-set.
#
# Track 05 uses the second-pass caption. The first version said "funky dream
# pop ... tight drum machine ... laid-back funk feel" and landed 39% of its
# energy in the 180-350 Hz snare body - audibly fatiguing. See artist-styles.md,
# "do not reach for funk".
#
# Usage:
#   ACESTEP_CONFIG_PATH=acestep-v15-xl-turbo .venv/bin/python acestep/api_server.py \
#       --host 127.0.0.1 --port 8001 &
#   bash .claude/skills/acestep-songwriting/references/playlist-mit8.sh /path/to/outdir
#   python scripts/audio_qc.py /path/to/outdir
#
set -u
cd /home/ding/ACE-Step-1.5
OUT="$1"
API=http://127.0.0.1:8001
MODEL=acestep-v15-xl-turbo
STEPS=8                 # turbo default; 20 is allowed but sounded worse here

# DCW at 0.01/0.005 is deliberately soft - it keeps the haze without smearing
# the bass transients that carry the hook.
run() {
  local name="$1" bpm="$2" key="$3" dur="$4" seed="$5" cap="$6" lyr="$7"
  echo "=== $name ($bpm $key ${dur}s seed=$seed) ==="
  .venv/bin/python acestep/api_client.py --base-url "$API" \
    --model "$MODEL" --prompt "$cap" --lyrics "$lyr" \
    --vocal-language en --bpm "$bpm" --key-scale "$key" --time-signature "4/4" \
    --inference-steps "$STEPS" --audio-duration "$dur" --seed "$seed" \
    --dcw-scaler 0.01 --dcw-high-scaler 0.005 \
    --output-dir "$OUT/$name" 2>&1 | grep -v libtinfo | tail -1
}

# ---------------------------------------------------------------- 01 ----
read -r -d '' C1 <<'EOF'
dreamy indie pop, soft breathy female vocal mixed low and close, melodic electric bass played with a pick carrying the main hook, clean electric guitar through chorus and flanger, warm FM electric piano, vintage drum machine with a fat snare, nostalgic and patient, warm lo-fi haze, unhurried groove, lots of space in the arrangement, self-produced indie studio
EOF
read -r -d '' L1 <<'EOF'
[Intro]

[Verse]
The light turns green at midnight
No one's behind me anyway
I keep my foot off the pedal
And let the whole thing wait

[Chorus]
I could go home
I could go home
But the radio's still warm
And I'm not done yet

[Verse]
Your jacket's on the back seat
It's been there for a week
I never bring it to you
I like the excuse to keep

[Chorus]
I could go home
I could go home
But the radio's still warm
And I'm not done yet

[Instrumental]

[Outro]
I could go home
(not done yet)

[Fade Out]
EOF

# ---------------------------------------------------------------- 02 ----
read -r -d '' C2 <<'EOF'
groovy dream pop, soft breathy female vocal mixed low, melodic picked electric bass as the lead hook instrument, out-of-phase clean electric guitar with phaser, warm FM electric piano chords, crisp vintage drum machine with a fat snare and tight hi-hat, laid-back but moving, warm analog haze, bittersweet and easygoing, self-produced indie studio
EOF
read -r -d '' L2 <<'EOF'
[Intro]

[Verse]
I know a street that loops around
It adds eleven minutes on
I take it when I'm not in a hurry
Which is most nights lately

[Pre-Chorus]
Nobody's counting
Nobody's counting

[Chorus]
Take the long way, take the long way
Nothing's waiting on the other side
Take the long way, take the long way
I'm fine with arriving late

[Verse]
There's a dog behind a blue fence
He barks the same each time
I say something back to him
It's the most I've talked all night

[Chorus]
Take the long way, take the long way
Nothing's waiting on the other side
Take the long way, take the long way
I'm fine with arriving late

[Guitar Solo]

[Outro]
Take the long way
(arriving late)

[Fade Out]
EOF

# ---------------------------------------------------------------- 03 ----
read -r -d '' C3 <<'EOF'
bright breezy dream pop, soft airy female vocal, bouncing picked electric bass line, jangly clean electric guitar with chorus, warm FM electric piano, light vintage drum machine groove, sunlit and nostalgic, warm tape saturation, open and spacious, carefree with a trace of melancholy, self-produced indie studio
EOF
read -r -d '' L3 <<'EOF'
[Intro]

[Verse]
Both windows down in April
The air still has an edge
You put your hand outside
And steer it like a wave

[Chorus]
Nothing's fixed, nothing's solved
But the song is good right now
Nothing's fixed, nothing's solved
And that's enough somehow

[Verse]
We don't talk about July
Or whose apartment stays
There's a bridge in eighteen seconds
And I want to see your face

[Chorus]
Nothing's fixed, nothing's solved
But the song is good right now
Nothing's fixed, nothing's solved
And that's enough somehow

[Instrumental]

[Outro]
That's enough somehow
(enough somehow)

[Fade Out]
EOF

# ---------------------------------------------------------------- 04 ----
read -r -d '' C4 <<'EOF'
upbeat dream pop with a driving groove, soft breathy female vocal mixed low, bright FM synthesizer lead line, punchy picked electric bass carrying the hook, clean electric guitar with chorus, crisp drum machine with a fat snare and tight hi-hat, bright and euphoric, warm analog sheen, eighties synth pop influence, self-produced indie studio
EOF
read -r -d '' L4 <<'EOF'
[Intro]

[Verse]
The on-ramp curves and opens
Four lanes and nobody here
The city drops behind us
Like it was never there

[Chorus]
Faster than I meant to
Faster than I meant to
I don't want to stop
I don't want to think

[Verse]
There's a truck with its lights off
Sitting on the shoulder lane
We pass it doing seventy
And neither of us explains

[Chorus]
Faster than I meant to
Faster than I meant to
I don't want to stop
I don't want to think

[Instrumental]

[Outro]
Faster than I meant to
(don't want to think)

[Fade Out]
EOF

# ---------------------------------------------------------------- 05 ----
# Second-pass caption: drums named once and qualified as muffled/dampened/
# tucked, bass explicitly named as loudest. No "funk" anywhere.
read -r -d '' C5 <<'EOF'
mellow dream pop with a gliding mid-tempo groove, soft breathy female vocal mixed low and close, warm round picked electric bass carrying the melody and sitting loudest in the mix, out-of-phase clean electric guitar with phaser and chorus, soft FM electric piano chords held long, muffled dampened drum machine tucked quietly behind the bass, soft brushed snare on a simple steady pattern, gentle and understated, warm analog haze, relaxed and spacious, self-produced indie studio
EOF
read -r -d '' L5 <<'EOF'
[Intro]

[Verse]
Pump four, the only one that's working
Fluorescent on an empty lot
You go inside for something
And take longer than you ought

[Pre-Chorus]
I don't mind waiting
I don't mind waiting

[Chorus]
Keep the motor running
Keep the motor running
Whatever this is
I'm not ready to end it

[Verse]
You come back with two coffees
And one of them is wrong
You drink the one you hate
And never say a word

[Chorus]
Keep the motor running
Keep the motor running
Whatever this is
I'm not ready to end it

[Guitar Solo]

[Outro]
Keep the motor running
(not ready to end it)

[Fade Out]
EOF

# ---------------------------------------------------------------- 06 ----
# Instrumental: the lyrics field still carries the structure, just no words.
read -r -d '' C6 <<'EOF'
instrumental dream pop, no vocals, melodic picked electric bass carrying the entire melody, clean electric guitar with chorus and flanger trading phrases, warm FM electric piano, soft vintage drum machine with a fat snare, hypnotic and looping, warm lo-fi haze, patient and spacious, self-produced indie studio
EOF
read -r -d '' L6 <<'EOF'
[Intro]

[Instrumental]

[Guitar Solo]

[Instrumental]

[Breakdown]

[Outro]

[Fade Out]
EOF

# ---------------------------------------------------------------- 07 ----
read -r -d '' C7 <<'EOF'
hazy slow dream pop, soft breathy female vocal drenched in plate reverb and mixed low, slow melodic electric bass, clean electric guitar with heavy chorus and long delay, warm FM electric piano, soft brushed drum machine, wistful and dissolving, thick warm haze, sparse arrangement with long gaps, self-produced indie studio
EOF
read -r -d '' L7 <<'EOF'
[Intro]

[Verse]
I park but leave it running
Then I cut the engine off
The quiet comes in sideways
Like it waited in the lot

[Chorus]
This is where it goes thin
This is where it goes thin
I can feel the night turn over
And I can't turn with it

[Verse]
The dashboard light stays orange
For a minute after off
I watch it until it's nothing
That's the part I like the most

[Chorus]
This is where it goes thin
This is where it goes thin
I can feel the night turn over
And I can't turn with it

[Breakdown]

[Outro]
Where it goes thin
(goes thin)

[Fade Out]
EOF

# ---------------------------------------------------------------- 08 ----
read -r -d '' C8 <<'EOF'
slow hazy dream pop, soft breathy female vocal mixed low and distant, warm melodic electric bass, clean electric guitar with heavy chorus and long delay, soft FM electric piano, brushed vintage drum machine, tender and resolved, thick warm tape haze, very spacious arrangement, long fade ending, self-produced indie studio
EOF
read -r -d '' L8 <<'EOF'
[Intro]

[Verse]
You fell asleep around five
Your head against the window
I drove another hour
Just so you could stay there

[Chorus]
It gets light so slow
It gets light so slow
Nothing has been decided
And nothing has been lost

[Verse]
The radio went to static
Somewhere past the county line
I left it on anyway
It sounded like the ocean

[Chorus]
It gets light so slow
It gets light so slow
Nothing has been decided
And nothing has been lost

[Instrumental]

[Outro]
It gets light so slow
(nothing has been lost)

[Fade Out]
EOF

run 01_green_light   95 "A Minor" 200 7301 "$C1" "$L1"
run 02_side_street  108 "E Minor" 195 7302 "$C2" "$L2"
run 03_tailwind     114 "C Major" 190 7303 "$C3" "$L3"
run 04_overpass     132 "E Major" 190 7401 "$C4" "$L4"
run 05_pump_four    120 "A Minor" 195 7432 "$C5" "$L5"
run 06_rest_stop    104 "G Major" 170 7403 "$C6" "$L6"
run 07_parking_lot   90 "A Minor" 200 7304 "$C7" "$L7"
run 08_sun_up        76 "E Minor" 215 7404 "$C8" "$L8"
