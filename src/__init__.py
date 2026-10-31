"""DataMate pipeline."""
import pandas as pd

try:  # pandas >= 3 infers a strict `str` dtype that rejects non-string assignments; keep the permissive object dtype
    pd.options.future.infer_string = False
except Exception:  # option missing in other versions: nothing to do
    pass
