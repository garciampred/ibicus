# (C) Copyright 1996- ECMWF.
#
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
# In applying this licence, ECMWF does not waive the privileges and immunities
# granted to it by virtue of its status as an intergovernmental organisation
# nor does it submit to any jurisdiction.

from logging import warning
from typing import Optional, Union

import attrs
import numpy as np

from ..utils import (
    RunningWindowOverYears,
    create_array_of_consecutive_dates,
    ecdf,
    iecdf,
    infer_and_create_time_arrays_if_not_given,
    month,
    year,
)
from ..variables import Variable, pr, tas
from ._debiaser import Debiaser

default_settings = {
    tas: {"SSR": False},
    pr: {"SSR": True},
}


@attrs.define
class CDFt(Debiaser):
    """
    Implements CDF-t following Michelangeli et al. 2009, Vrac et al. 2012, Famien et al. 2018 and Vrac et al. 2016 for precipitation.
    Let cm refer to climate model output, obs to observations and hist/future to whether the data was collected from the reference period or is part of future projections.
    Let :math:`F` be an empirical cdf. The future climate projections :math:`x_{\\text{cm_fut}}` are then mapped using a QQ-mapping between :math:`F_{\\text{cm_fut}}` and :math:`F_{\\text{obs_fut}}`, with:

    .. math:: F_{\\text{obs_fut}} := F_{\\text{obs_hist}}(F^-1_{\\text{cm_hist}}(F_{\\text{cm_fut}})).

    This means that :math:`x_{\\text{cm_fut}}` is mapped using the following:

    .. math:: x_{\\text{cm_fut}} \\rightarrow F^{-1}_{\\text{obs_fut}}(F_{\\text{cm_fut}}(x_{\\text{cm_fut}})) = F^{-1}_{\\text{cm_fut}}(F_{\\text{cm_hist}}(F^{-1}_{\\text{obs_hist}}(F_{\\text{cm_fut}}(x_{\\text{cm_fut}}))))

    All cdfs here are estimated empirically.

    In case a delta_shift is used the future and historical climate model run are either additively shifted by the difference between observational mean and historical climate model mean or multiplicatively by the quotient between observational mean and historical climate model one. This means for an additive delta shift:

    .. math:: x_{\\text{cm_fut}} \\rightarrow x_{\\text{cm_fut}} + \\bar x_{\\text{obs}} - \\bar x_{\\text{cm_hist}}
    .. math:: x_{\\text{cm_hist}} \\rightarrow x_{\\text{cm_hist}} + \\bar x_{\\text{obs}} - \\bar x_{\\text{cm_hist}}

    and for a multiplicative delta shift:

    .. math:: x_{\\text{cm_fut}} \\rightarrow x_{\\text{cm_fut}} \\cdot \\frac{\\bar x_{\\text{obs}}}{\\bar x_{\\text{cm_hist}}}
    .. math:: x_{\\text{cm_hist}} \\rightarrow x_{\\text{cm_hist}} \\cdot \\frac{\\bar x_{\\text{obs}}}{\\bar x_{\\text{cm_hist}}}

    Here :math:`\\bar x` stands for the mean over all x-values.

    This does an additional shift by the mean absolute or relative bias and ensures that the range of observations and cm_hist is approximately similar (important for the empirical CDFs).

    If self.SSR = True then Stochastic Singularity Removal (SSR) following Vrac et al. 2016 is used to correct the occurrence in addition to amounts (default for Precipitation). In there all zero values are first replaced by uniform draws between 0 and a small threshold (the minimum positive value of observation and model data). Then CDFt-mapping is used and afterwards all observations under the threshold are set to zero again.
    If self.apply_by_month = True (default) then CDF-t is applied by month following Famien et al. 2018 to take into account seasonality. Otherwise the method is applied to the whole year.
    If self.running_window_mode = True (default) then the method is used in a running window mode, running over the values of the future climate model. This helps to smooth discontinuities.

    .. warning:: Currently only uneven sizes are allowed for window length and window step length. This allows symmetrical windows of the form [window_center - window length//2, window_center + window length//2] given an arbitrary window center.

    **References**:

    - Michelangeli, P.-A., Vrac, M., & Loukos, H. (2009). Probabilistic downscaling approaches: Application to wind cumulative distribution functions. In Geophysical Research Letters (Vol. 36, Issue 11). American Geophysical Union (AGU). https://doi.org/10.1029/2009gl038401
    - Famien, A. M., Janicot, S., Ochou, A. D., Vrac, M., Defrance, D., Sultan, B., & Noël, T. (2018). A bias-corrected CMIP5 dataset for Africa using the CDF-t method – a contribution to agricultural impact studies. In Earth System Dynamics (Vol. 9, Issue 1, pp. 313–338). Copernicus GmbH. https://doi.org/10.5194/esd-9-313-2018
    - Vrac, M., Drobinski, P., Merlo, A., Herrmann, M., Lavaysse, C., Li, L., & Somot, S. (2012). Dynamical and statistical downscaling of the French Mediterranean climate: uncertainty assessment. In Natural Hazards and Earth System Sciences (Vol. 12, Issue 9, pp. 2769–2784). Copernicus GmbH. https://doi.org/10.5194/nhess-12-2769-2012
    - Vrac, M., Noël, T., & Vautard, R. (2016). Bias correction of precipitation through Singularity Stochastic Removal: Because occurrences matter. In Journal of Geophysical Research: Atmospheres (Vol. 121, Issue 10, pp. 5237–5258). American Geophysical Union (AGU). https://doi.org/10.1002/2015jd024511


    Attributes
    ----------
    SSR: bool
        If Stochastic Singularity Removal (SSR) following Vrac et al. 2016 is applied to adjust the number of zero values (only relevant for precipitation).
    delta_shift: str
        One of ["additive", "multiplicative", "no_shift"]. What kind of shift is applied to the data prior to fitting empirical distributions.
    apply_by_month: bool
        Whether CDF-t is applied month by month (default) to account for seasonality or onto the whole dataset at once.
    running_window_mode: bool
        Whether CDF-t is used in running window mode, running over the values of the future climate model to help smooth discontinuities.
    running_window_length_in_years: int
        Length of the running window in years: how many values are used to calculate the empirical CDF. Only relevant if running_window_mode = True.
    running_window_step_length_in_years: int
        Step length of the running window in years: how many values are debiased inside the running window. Only relevant if running_window_mode = True.
    variable: str
        Variable for which the debiasing is done. Default: "unknown".
    ecdf_method: str
        One of ["kernel_density", "linear_interpolation", "step_function"], default: "linear_interpolation". Method to calculate the empirical CDF
    iecdf_method: str
        One of ["inverted_cdf","averaged_inverted_cdf", closest_observation","interpolated_inverted_cdf","hazen","weibull","linear","median_unbiased","normal_unbiased"], default "linear". Method to calculate the inverse empirical CDF (empirical quantile function).
    """

    # CDFt parameters
    SSR: bool = attrs.field(default=False, validator=attrs.validators.instance_of(bool))
    delta_shift: str = attrs.field(
        default="additive", validator=attrs.validators.in_(["additive", "multiplicative", "no_shift"])
    )

    # Iteration parameters
    apply_by_month: bool = attrs.field(default=True, validator=attrs.validators.instance_of(bool))
    running_window_mode: bool = attrs.field(default=True, validator=attrs.validators.instance_of(bool))
    running_window_length_in_years: int = attrs.field(default=17, validator=attrs.validators.instance_of(int))
    running_window_step_length_in_years: int = attrs.field(default=9, validator=attrs.validators.instance_of(int))

    # Variable meta information
    variable: str = attrs.field(default="unknown", eq=False)

    # Calculation parameters
    ecdf_method: str = attrs.field(
        default="linear_interpolation",
        validator=attrs.validators.in_(["kernel_density", "linear_interpolation", "step_function"]),
    )
    iecdf_method: str = attrs.field(
        default="linear",
        validator=attrs.validators.in_(
            [
                "inverted_cdf",
                "averaged_inverted_cdf",
                "closest_observation",
                "interpolated_inverted_cdf",
                "hazen",
                "weibull",
                "linear",
                "median_unbiased",
                "normal_unbiased",
            ]
        ),
    )

    def __attrs_post_init__(self):
        if self.running_window_mode:
            self.running_window = RunningWindowOverYears(
                window_length_in_years=self.running_window_length_in_years,
                window_step_length_in_years=self.running_window_step_length_in_years,
            )

    @classmethod
    def from_variable(cls, variable: Union[str, Variable], **kwargs):
        return super().from_variable(cls, variable, default_settings, **kwargs)

    # ----- Helpers: General ----- #
    @staticmethod
    def _check_time_information_and_raise_error(obs, cm_hist, cm_future, time_obs, time_cm_hist, time_cm_future):
        if obs.size != time_obs.size or cm_hist.size != time_cm_hist.size or cm_future.size != time_cm_future.size:
            raise ValueError(
                """Dimensions of time information for one of time_obs, time_cm_hist, time_cm_future do not correspond to the dimensions of obs, cm_hist, cm_future. 
                Make sure that for each one of obs, cm_hist, cm_future time information is given for each value in the arrays."""
            )

    # ----- Helpers: CDFt application -----#

    def _apply_CDFt_mapping(self, obs, cm_hist, cm_future):

        if self.delta_shift == "additive":
            shift = np.mean(obs) - np.mean(cm_hist)
            cm_hist = cm_hist + shift
            cm_future = cm_future + shift
        elif self.delta_shift == "multiplicative":
            shift = np.mean(obs) / np.mean(cm_hist)
            cm_hist = cm_hist * shift
            cm_future = cm_future * shift
        elif self.delta_shift == "no_shift":
            pass
        else:
            raise ValueError('self.delta_shift needs to be one of ["additive", "multiplicative", "no_shift"]')

        return iecdf(
            x=cm_future,
            p=ecdf(
                x=cm_hist,
                y=iecdf(x=obs, p=ecdf(x=cm_future, y=cm_future, method=self.ecdf_method), method=self.iecdf_method),
                method=self.ecdf_method,
            ),
            method=self.iecdf_method,
        )

    @staticmethod
    def _get_threshold(obs, cm_hist, cm_future):
        return min(obs[obs > 0].min(), cm_hist[cm_hist > 0].min(), cm_future[cm_future > 0].min())

    @staticmethod
    def _randomize_zero_values_between_zero_and_threshold(x, threshold):
        return np.where(x == 0, np.random.uniform(low=0, high=threshold, size=x.size), x)

    @staticmethod
    def _set_values_below_threshold_to_zero(x, threshold):
        return np.where(x < threshold, 0, x)

    @staticmethod
    def _apply_SSR_steps_before_adjustment(obs, cm_hist, cm_future):
        threshold = CDFt._get_threshold(obs, cm_hist, cm_future)

        obs = CDFt._randomize_zero_values_between_zero_and_threshold(obs, threshold)
        cm_hist = CDFt._randomize_zero_values_between_zero_and_threshold(cm_hist, threshold)
        cm_future = CDFt._randomize_zero_values_between_zero_and_threshold(cm_future, threshold)
        return obs, cm_hist, cm_future, threshold

    @staticmethod
    def _apply_SSR_steps_after_adjustment(cm_future, threshold):
        cm_future = CDFt._set_values_below_threshold_to_zero(cm_future, threshold)
        return cm_future

    def _apply_on_month_and_window(self, obs: np.ndarray, cm_hist: np.ndarray, cm_future: np.ndarray):

        # Precipitation
        if self.SSR:
            obs, cm_hist, cm_future, threshold = CDFt._apply_SSR_steps_before_adjustment(obs, cm_hist, cm_future)

        cm_future = self._apply_CDFt_mapping(obs, cm_hist, cm_future)

        # Precipitation
        if self.SSR:
            cm_future = CDFt._apply_SSR_steps_after_adjustment(cm_future, threshold)

        return cm_future

    def _apply_on_window(
        self,
        obs: np.ndarray,
        cm_hist: np.ndarray,
        cm_future: np.ndarray,
        time_obs: Optional[np.ndarray] = None,
        time_cm_hist: Optional[np.ndarray] = None,
        time_cm_future: Optional[np.ndarray] = None,
    ):

        if self.apply_by_month:
            debiased_cm_future = np.empty_like(cm_future)
            for i_month in range(1, 13):
                mask_i_month_in_obs_hist = month(time_obs) == i_month
                mask_i_month_in_cm_hist = month(time_cm_hist) == i_month
                mask_i_month_in_cm_future = month(time_cm_future) == i_month

                debiased_cm_future[mask_i_month_in_cm_future] = self._apply_on_month_and_window(
                    obs=obs[mask_i_month_in_obs_hist],
                    cm_hist=cm_hist[mask_i_month_in_cm_hist],
                    cm_future=cm_future[mask_i_month_in_cm_future],
                )
            return debiased_cm_future
        else:
            return self._apply_on_month_and_window(obs=obs, cm_hist=cm_hist, cm_future=cm_future)

    def apply_location(
        self,
        obs: np.ndarray,
        cm_hist: np.ndarray,
        cm_future: np.ndarray,
        time_obs: Optional[np.ndarray] = None,
        time_cm_hist: Optional[np.ndarray] = None,
        time_cm_future: Optional[np.ndarray] = None,
    ):

        if time_obs is None or time_cm_hist is None or time_cm_future is None:
            warning(
                """
                    CDF-t runs without time-information for at least one of obs, cm_hist or cm_future.
                    This information is inferred, assuming the first observation is on a January 1st. Observations are chunked according to the assumed time information. 
                    This might lead to slight numerical differences to the run with time information, however the debiasing is not fundamentally changed.
                    """
            )
            time_obs, time_cm_hist, time_cm_future = infer_and_create_time_arrays_if_not_given(
                obs, cm_hist, cm_future, time_obs, time_cm_hist, time_cm_future
            )

        CDFt._check_time_information_and_raise_error(obs, cm_hist, cm_future, time_obs, time_cm_hist, time_cm_future)

        if self.running_window_mode:
            years_cm_future = year(time_cm_future)

            debiased_cm_future = np.empty_like(cm_future)
            for years_to_debias, years_in_window in self.running_window.use(years_cm_future):

                mask_years_in_window = RunningWindowOverYears.get_if_in_chosen_years(years_cm_future, years_in_window)
                mask_years_to_debias = RunningWindowOverYears.get_if_in_chosen_years(years_cm_future, years_to_debias)
                mask_years_in_window_to_debias = RunningWindowOverYears.get_if_in_chosen_years(
                    years_cm_future[mask_years_in_window], years_to_debias
                )

                debiased_cm_future[mask_years_to_debias] = self._apply_on_window(
                    obs=obs,
                    cm_hist=cm_hist,
                    cm_future=cm_future[mask_years_in_window],
                    time_obs=time_obs,
                    time_cm_hist=time_cm_hist,
                    time_cm_future=time_cm_future[mask_years_in_window],
                )[mask_years_in_window_to_debias]

            return debiased_cm_future

        else:
            return self._apply_on_window(obs, cm_hist, cm_future, time_obs, time_cm_hist, time_cm_future)
