"""One content width for every page.

Each page used to pick its own clamp, so switching tabs moved the content
edges around: 880 on Voice, 1040 on Microphone and Deck, 1180 on Effects and
the mixer's bus meters. The widest page sets the standard, because the EQ
curve and the compressor waveform are the content that actually needs room.
"""

CONTENT_WIDTH = 1180
TIGHTENING = 760
