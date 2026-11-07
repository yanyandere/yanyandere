"""LAION-CLAP (laion/larger_clap_general) text-audio similarity, run in .venv-clap.

laion/larger_clap_music is not used: its published text tower is collapsed
(cosine 0.999 between unrelated prompts, logit scale 1.0), so it cannot rank
descriptions.

usage: clap_check.py song.wav sections.json -> JSON on stdout
sections.json: {"name": [start_s, end_s], ...}
"""
import json
import sys

import librosa
import numpy as np
import torch
from transformers import ClapModel, ClapProcessor

STYLE = {  # does the whole song sound like the brief, rather than something else?
    "melancholic 1970s orchestral jazz with strings, flugelhorn and electric piano": True,
    "a bittersweet cinematic anime soundtrack, hopeful yet tragic": True,
    "an emotional orchestral film score with jazz harmony": True,
    "a sad but hopeful video game soundtrack with strings and piano": True,
    "upbeat electronic dance music with a four-on-the-floor beat": False,
    "aggressive heavy metal with distorted guitars": False,
    "a lo-fi hip hop beat": False,
    "a cheerful children's song": False,
    "a solo acoustic guitar folk song with vocals": False,
    "trap music with 808 bass": False,
    "an ambient drone soundscape": False,
}
NARRATIVE = {  # does each section tell its part of the story?
    "tragic": "a tragic, mournful orchestral lament",
    "battle": "an epic, driving orchestral battle theme with drums and brass",
    "tender": "a gentle, tender music box and electric piano melody",
    "hopeful": "a hopeful, uplifting melody",
}
MODEL = "laion/larger_clap_general"
SR = 48000
WIN = 10


def feats(o):
    return o if isinstance(o, torch.Tensor) else o.pooler_output  # transformers >= 5 returns a ModelOutput


def main(wav: str, sections_path: str) -> None:
    sections = json.load(open(sections_path))
    y, _ = librosa.load(wav, sr=SR, mono=True)
    model = ClapModel.from_pretrained(MODEL).eval()
    proc = ClapProcessor.from_pretrained(MODEL)
    texts = list(STYLE) + list(NARRATIVE.values())
    with torch.no_grad():
        t = feats(model.get_text_features(**proc(text=texts, return_tensors="pt", padding=True)))
    t = torch.nn.functional.normalize(t, dim=-1)

    def embed(a, b):
        chunks = [y[i:i + WIN * SR] for i in range(int(a * SR), max(int(a * SR) + 1, int(b * SR) - WIN * SR + 1), 5 * SR)]
        chunks = [c for c in chunks if len(c) >= SR * 3]
        try:
            inp = proc(audio=chunks, sampling_rate=SR, return_tensors="pt")
        except TypeError:
            inp = proc(audios=chunks, sampling_rate=SR, return_tensors="pt")
        with torch.no_grad():
            e = feats(model.get_audio_features(**inp))
        return torch.nn.functional.normalize(e, dim=-1)

    whole = (embed(0, len(y) / SR) @ t.T).mean(0).numpy()
    style = {k: round(float(whole[i]), 4) for i, k in enumerate(STYLE)}
    narrative = {}
    for name, (a, b) in sections.items():
        sims = (embed(a, b) @ t.T).mean(0).numpy()[len(STYLE):]
        narrative[name] = {k: round(float(s), 4) for k, s in zip(NARRATIVE, sims)}
    pos = [v for k, v in style.items() if STYLE[k]]
    neg = [v for k, v in style.items() if not STYLE[k]]
    print(json.dumps(dict(style=style, best=max(style, key=style.get), best_is_target=STYLE[max(style, key=style.get)],
                          mean_target=round(float(np.mean(pos)), 4), max_other=round(float(np.max(neg)), 4),
                          narrative=narrative)))


if __name__ == "__main__":
    main(*sys.argv[1:])
