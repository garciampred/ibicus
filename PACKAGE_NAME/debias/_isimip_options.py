# (C) Copyright 1996- ECMWF.
#
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
# In applying this licence, ECMWF does not waive the privileges and immunities
# granted to it by virtue of its status as an intergovernmental organisation
# nor does it submit to any jurisdiction.

import numpy as np
import scipy.stats

from ..variables import (
    hurs,
    pr,
    prsnratio,
    psl,
    rlds,
    rsds,
    sfcwind,
    tas,
    tasrange,
    tasskew,
)

# General settings (non variable specific, might be overwritten by variable-settings)
isimip3_general_settings = {
    # ISIMIP behavior
    "trend_removal_with_significance_test": True,  # >= v2.1, step 3
    # Math helpers
    "ecdf_method": "linear_interpolation",
    "iecdf_method": "linear",
    "mode_non_parametric_quantile_mapping": "isimipv3.0",  # >= v2.4, step 6
    # Iteration
    "running_window_mode": True,  # >= v2.5
    "running_window_length": 31,  # >= v2.5
    "running_window_step_length": 1,  # >= v2.5
    # Standard algorithm behavior (overwritten by variables potentially)
    "scale_by_annual_cycle_of_upper_bounds": False,  # step 1
    "window_length_annual_cycle_of_upper_bounds": 31,  # step 1
    "impute_missing_values": False,  # step 2
    "detrending": False,  # step 3
    "trend_transfer_only_for_values_within_threshold": True,  # >= v2.4,  step 5
    "ks_test_for_goodness_of_cdf_fit": True,  # step 6
    "nonparametric_qm": False,  # >= v2.4.1 step 6
    "event_likelihood_adjustment": False,  # >= v2.5 step 6
    "adjust_frequencies_of_values_beyond_thresholds": True,  # v >= 2.5, step 6
}

# Variable settings: controlling behavior for individual variables
isimip3_variable_settings = {
    hurs: {
        "lower_bound": 0,
        "lower_threshold": 0.01,
        "upper_bound": 100,
        "upper_threshold": 99.99,
        "distribution": scipy.stats.beta,
        "trend_preservation_method": "bounded",
        "nonparametric_qm": True,  # >= v2.4.1 step 6
        "trend_transfer_only_for_values_within_threshold": False,  # >= v2.4,  step 5
        "adjust_frequencies_of_values_beyond_thresholds": False,  # v >= 2.5, step 6
    },
    pr: {
        "lower_bound": 0,
        "lower_threshold": 0.1 / 86400,
        "upper_bound": np.inf,
        "upper_threshold": np.inf,
        "distribution": scipy.stats.gamma,
        "trend_preservation_method": "mixed",
    },
    prsnratio: {
        "lower_bound": 0,
        "lower_threshold": 0.0001,
        "upper_bound": 1,
        "upper_threshold": 0.9999,
        "distribution": scipy.stats.beta,
        "trend_preservation_method": "bounded",
        "impute_missing_values": True,  # step 2
        "nonparametric_qm": True,  # >= v2.4.1 step 6
    },
    psl: {
        "lower_bound": -np.inf,
        "lower_threshold": -np.inf,
        "upper_bound": np.inf,
        "upper_threshold": np.inf,
        "distribution": scipy.stats.norm,
        "trend_preservation_method": "additive",
        "detrending": True,
    },
    rsds: {
        "lower_bound": 0,
        "lower_threshold": 0.0001,
        "upper_bound": 1,
        "upper_threshold": 0.9999,
        "distribution": scipy.stats.beta,
        "trend_preservation_method": "bounded",
        "scale_by_annual_cycle_of_upper_bounds": True,  # step 1
        "window_length_annual_cycle_of_upper_bounds": 31,  # step 1
        "nonparametric_qm": True,  # >= v2.4.1 step 6
    },
    rlds: {
        "lower_bound": -np.inf,
        "lower_threshold": -np.inf,
        "upper_bound": np.inf,
        "upper_threshold": np.inf,
        "distribution": scipy.stats.norm,
        "trend_preservation_method": "additive",
        "detrending": True,
    },
    sfcwind: {
        "lower_bound": 0,
        "lower_threshold": 0.01,
        "upper_bound": np.inf,
        "upper_threshold": np.inf,
        "distribution": scipy.stats.weibull_min,  # TODO: needs to be real weibull (log of exponweib)
        "trend_preservation_method": "mixed",
    },
    tas: {
        "lower_bound": -np.inf,
        "lower_threshold": -np.inf,
        "upper_bound": np.inf,
        "upper_threshold": np.inf,
        "distribution": scipy.stats.norm,
        "trend_preservation_method": "additive",
        "detrending": True,
        "reasonable_physical_range": [0, 400],  # TODO: needs to appear everywhere
    },
    tasrange: {
        "lower_bound": 0,
        "lower_threshold": 0.01,
        "upper_bound": np.inf,
        "upper_threshold": np.inf,
        "distribution": scipy.stats.weibull_min,  # was rice in paper but is weibull in command
        "trend_preservation_method": "mixed",
    },
    tasskew: {
        "lower_bound": 0,
        "lower_threshold": 0.0001,
        "upper_bound": 1,
        "upper_threshold": 0.9999,
        "distribution": scipy.stats.beta,
        "trend_preservation_method": "bounded",
        "nonparametric_qm": True,  # >= v2.4.1 step 6
    },
}
