"""latam_eda, read-only, for scripts: `from report_lib.eda import data, granularity, pipeline`
(and the forensics modules `change_detection`, `raw_forensics`).

Importing through report_lib guarantees the package init has put ../eda/src on sys.path first, whatever order an
import sorter gives the lines of a script.
"""

from latam_eda import change_detection, data, granularity, pipeline, raw_forensics
from report_lib import _EDA_SRC as EDA_SRC

__all__ = ["EDA_SRC", "change_detection", "data", "granularity", "pipeline", "raw_forensics"]
