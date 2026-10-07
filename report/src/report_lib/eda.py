"""latam_eda, read-only, for scripts: `from report_lib.eda import data, granularity, pipeline`.

Importing through report_lib guarantees the package init has put ../eda/src on sys.path first, whatever order an
import sorter gives the lines of a script.
"""

from latam_eda import data, granularity, pipeline
from report_lib import _EDA_SRC as EDA_SRC

__all__ = ["EDA_SRC", "data", "granularity", "pipeline"]
