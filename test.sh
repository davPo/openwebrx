#!/bin/bash

rtl_sdr -s 2400000 -f 145442000 - | csdr convert_u8_f | csdr fmdemod_quadri_cf | csdr fractional_decimator_ff 5 | csdr convert_f_s16 | sox -V -t raw -r 48000 -e signed-integer -b 16 -c 1 - -t raw -r 48000 -e signed-integer -b 32 -c 1  -L - | cmx882_decoder -s65535 -d3 | gpsmic_decoder -o4
