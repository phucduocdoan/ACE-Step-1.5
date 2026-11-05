#!/usr/bin/env bash
#
# Vietnamese-language rewrite of the eight-track set in playlist-mit8.sh.
#
# Deliberately a controlled comparison, not a new record: captions, seeds, bpm,
# key, duration and sampler settings are byte-identical to the English script.
# The only things that change are the lyrics and --vocal-language. If these
# come out worse, the language is the reason, not the arrangement.
#
# The lyrics are rewritten, not translated. Vietnamese is monosyllabic and
# tonal, so a literal translation blows the syllable count and scans badly;
# each line was re-written to the original's syllable count (+/-1) and its
# plain, unadorned register. One image per song, same image as the original.
#
# Track 06 is instrumental and has no words, so there is nothing to translate.
# It is copied from the English set rather than regenerated, so this script
# emits seven files, not eight.
#
# Verified by md5 against the shipped audio:
#   a877e99471fa6a3797233e01694004e7  01_green_light.mp3
#   609adfc643e654c3880aff5e4dd394eb  02_side_street.mp3
#   99e02ed3bef1c3a09c70a2bf73eb474b  03_tailwind.mp3
#   2119bce27064551e3629cf93ea4a8843  04_overpass.mp3
#   81e5c8a8663480e0244ae53cc8aa0894  05_pump_four.mp3
#   a140355b4d64a6bd6a5d11ee96bfb831  07_parking_lot.mp3
#   d21a15355d26ba4f5908bfb33e8f3cf0  08_sun_up.mp3
#
# Usage:
#   ACESTEP_CONFIG_PATH=acestep-v15-xl-turbo .venv/bin/python acestep/api_server.py \
#       --host 127.0.0.1 --port 8001 &
#   bash .claude/skills/acestep-songwriting/references/playlist-mit8-vi.sh /path/to/outdir
#   cp samples/playlist/06_rest_stop.mp3 /path/to/outdir/
#   python scripts/audio_qc.py /path/to/outdir
#
set -u
cd /home/ding/ACE-Step-1.5
OUT="$1"
API=http://127.0.0.1:8001
MODEL=acestep-v15-xl-turbo
STEPS=8

run() {
  local name="$1" bpm="$2" key="$3" dur="$4" seed="$5" cap="$6" lyr="$7"
  echo "=== $name ($bpm $key ${dur}s seed=$seed) ==="
  .venv/bin/python acestep/api_client.py --base-url "$API" \
    --model "$MODEL" --prompt "$cap" --lyrics "$lyr" \
    --vocal-language vi --bpm "$bpm" --key-scale "$key" --time-signature "4/4" \
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
Đèn chuyển xanh lúc nửa đêm
Phía sau cũng chẳng có ai
Chân mình không chạm lên ga
Cứ để đó, chờ thêm

[Chorus]
Mình về được rồi
Mình về được rồi
Nhưng radio còn ấm
Mà mình chưa muốn dừng

[Verse]
Áo khoác cậu ở ghế sau
Để đó cả tuần nay rồi
Mình chưa mang trả lần nào
Thích giữ cái cớ đó thôi

[Chorus]
Mình về được rồi
Mình về được rồi
Nhưng radio còn ấm
Mà mình chưa muốn dừng

[Instrumental]

[Outro]
Mình về được rồi
(chưa muốn dừng)

[Fade Out]
EOF

# ---------------------------------------------------------------- 02 ----
read -r -d '' C2 <<'EOF'
groovy dream pop, soft breathy female vocal mixed low, melodic picked electric bass as the lead hook instrument, out-of-phase clean electric guitar with phaser, warm FM electric piano chords, crisp vintage drum machine with a fat snare and tight hi-hat, laid-back but moving, warm analog haze, bittersweet and easygoing, self-produced indie studio
EOF
read -r -d '' L2 <<'EOF'
[Intro]

[Verse]
Có con đường vòng mình hay đi
Đi thêm mười một phút thôi
Mình chọn nó những hôm không vội
Mà dạo này gần như mỗi đêm

[Pre-Chorus]
Chẳng ai đếm đâu
Chẳng ai đếm đâu

[Chorus]
Đi đường vòng, đi đường vòng
Đầu bên kia chẳng có gì đợi
Đi đường vòng, đi đường vòng
Đến muộn một chút cũng không sao

[Verse]
Có con chó sau hàng rào xanh
Lần nào cũng sủa y nhau
Mình đáp lại nó một câu
Câu duy nhất mình nói cả đêm

[Chorus]
Đi đường vòng, đi đường vòng
Đầu bên kia chẳng có gì đợi
Đi đường vòng, đi đường vòng
Đến muộn một chút cũng không sao

[Guitar Solo]

[Outro]
Đi đường vòng
(đến muộn thôi)

[Fade Out]
EOF

# ---------------------------------------------------------------- 03 ----
read -r -d '' C3 <<'EOF'
bright breezy dream pop, soft airy female vocal, bouncing picked electric bass line, jangly clean electric guitar with chorus, warm FM electric piano, light vintage drum machine groove, sunlit and nostalgic, warm tape saturation, open and spacious, carefree with a trace of melancholy, self-produced indie studio
EOF
read -r -d '' L3 <<'EOF'
[Intro]

[Verse]
Tháng Tư hạ hết hai cửa kính
Gió vẫn còn sắc một chút
Cậu đưa tay ra ngoài xe
Lượn như đang rẽ sóng

[Chorus]
Chẳng sửa gì, chẳng xong gì
Nhưng bài này đang hay mà
Chẳng sửa gì, chẳng xong gì
Vậy mà cũng đủ rồi

[Verse]
Mình không nhắc chuyện tháng Bảy
Hay ai sẽ giữ căn phòng
Mười tám giây nữa tới khúc hay
Mình muốn nhìn mặt cậu

[Chorus]
Chẳng sửa gì, chẳng xong gì
Nhưng bài này đang hay mà
Chẳng sửa gì, chẳng xong gì
Vậy mà cũng đủ rồi

[Instrumental]

[Outro]
Vậy mà cũng đủ rồi
(đủ rồi thôi)

[Fade Out]
EOF

# ---------------------------------------------------------------- 04 ----
read -r -d '' C4 <<'EOF'
upbeat dream pop with a driving groove, soft breathy female vocal mixed low, bright FM synthesizer lead line, punchy picked electric bass carrying the hook, clean electric guitar with chorus, crisp drum machine with a fat snare and tight hi-hat, bright and euphoric, warm analog sheen, eighties synth pop influence, self-produced indie studio
EOF
read -r -d '' L4 <<'EOF'
[Intro]

[Verse]
Đường dẫn cong rồi mở ra
Bốn làn và chẳng có ai
Thành phố rơi lại phía sau
Như chưa từng ở đó

[Chorus]
Nhanh hơn mình định đi
Nhanh hơn mình định đi
Mình không muốn dừng
Mình không muốn nghĩ

[Verse]
Có chiếc xe tải tắt đèn
Đứng im bên làn khẩn cấp
Mình vượt qua ở bảy mươi
Và cả hai đều không nói

[Chorus]
Nhanh hơn mình định đi
Nhanh hơn mình định đi
Mình không muốn dừng
Mình không muốn nghĩ

[Instrumental]

[Outro]
Nhanh hơn mình định đi
(không muốn nghĩ)

[Fade Out]
EOF

# ---------------------------------------------------------------- 05 ----
read -r -d '' C5 <<'EOF'
mellow dream pop with a gliding mid-tempo groove, soft breathy female vocal mixed low and close, warm round picked electric bass carrying the melody and sitting loudest in the mix, out-of-phase clean electric guitar with phaser and chorus, soft FM electric piano chords held long, muffled dampened drum machine tucked quietly behind the bass, soft brushed snare on a simple steady pattern, gentle and understated, warm analog haze, relaxed and spacious, self-produced indie studio
EOF
read -r -d '' L5 <<'EOF'
[Intro]

[Verse]
Trụ bốn, cái duy nhất còn chạy
Đèn huỳnh quang trên sân trống
Cậu vào trong mua gì đó
Rồi ở lâu hơn mức cần

[Pre-Chorus]
Mình không ngại chờ
Mình không ngại chờ

[Chorus]
Cứ để máy nổ đi
Cứ để máy nổ đi
Dù đây là cái gì
Mình chưa muốn kết thúc

[Verse]
Cậu cầm ra hai ly cà phê
Một ly là gọi nhầm
Cậu uống ly cậu ghét
Và không nói câu nào

[Chorus]
Cứ để máy nổ đi
Cứ để máy nổ đi
Dù đây là cái gì
Mình chưa muốn kết thúc

[Guitar Solo]

[Outro]
Cứ để máy nổ đi
(chưa muốn kết thúc)

[Fade Out]
EOF

# ---------------------------------------------------------------- 07 ----
read -r -d '' C7 <<'EOF'
hazy slow dream pop, soft breathy female vocal drenched in plate reverb and mixed low, slow melodic electric bass, clean electric guitar with heavy chorus and long delay, warm FM electric piano, soft brushed drum machine, wistful and dissolving, thick warm haze, sparse arrangement with long gaps, self-produced indie studio
EOF
read -r -d '' L7 <<'EOF'
[Intro]

[Verse]
Đỗ xe nhưng chưa tắt máy
Rồi mình tắt máy đi
Tiếng im lặng tràn vào ngang
Như đã chờ sẵn ngoài sân

[Chorus]
Chỗ này mọi thứ mỏng đi
Chỗ này mọi thứ mỏng đi
Mình thấy đêm đang lật mình
Mà mình không lật theo được

[Verse]
Đèn táp-lô còn cam một lúc
Sau khi đã tắt máy rồi
Mình nhìn tới khi nó tắt hẳn
Đó là đoạn mình thích nhất

[Chorus]
Chỗ này mọi thứ mỏng đi
Chỗ này mọi thứ mỏng đi
Mình thấy đêm đang lật mình
Mà mình không lật theo được

[Breakdown]

[Outro]
Chỗ mọi thứ mỏng đi
(mỏng đi)

[Fade Out]
EOF

# ---------------------------------------------------------------- 08 ----
read -r -d '' C8 <<'EOF'
slow hazy dream pop, soft breathy female vocal mixed low and distant, warm melodic electric bass, clean electric guitar with heavy chorus and long delay, soft FM electric piano, brushed vintage drum machine, tender and resolved, thick warm tape haze, very spacious arrangement, long fade ending, self-produced indie studio
EOF
read -r -d '' L8 <<'EOF'
[Intro]

[Verse]
Cậu ngủ quên lúc năm giờ
Đầu tựa vào bên cửa kính
Mình chạy thêm một tiếng nữa
Chỉ để cậu nằm yên đó

[Chorus]
Trời sáng chậm thật
Trời sáng chậm thật
Chẳng có gì được quyết
Và cũng chẳng mất gì

[Verse]
Radio chuyển thành tiếng nhiễu
Qua khỏi địa phận tỉnh rồi
Mình vẫn để nguyên như thế
Nghe cứ như tiếng biển

[Chorus]
Trời sáng chậm thật
Trời sáng chậm thật
Chẳng có gì được quyết
Và cũng chẳng mất gì

[Instrumental]

[Outro]
Trời sáng chậm thật
(chẳng mất gì cả)

[Fade Out]
EOF

run 01_green_light   95 "A Minor" 200 7301 "$C1" "$L1"
run 02_side_street  108 "E Minor" 195 7302 "$C2" "$L2"
run 03_tailwind     114 "C Major" 190 7303 "$C3" "$L3"
run 04_overpass     132 "E Major" 190 7401 "$C4" "$L4"
run 05_pump_four    120 "A Minor" 195 7432 "$C5" "$L5"
run 07_parking_lot   90 "A Minor" 200 7304 "$C7" "$L7"
run 08_sun_up        76 "E Minor" 215 7404 "$C8" "$L8"
echo "ALL DONE"
