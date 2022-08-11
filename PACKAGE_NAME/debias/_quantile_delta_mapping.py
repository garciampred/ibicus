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
import scipy

from ..utils import (
    RunningWindowOverDaysOfYear,
    RunningWindowOverYears,
    StatisticalModel,
    day_of_year,
    ecdf,
    gen_PrecipitationGammaLeftCensoredModel,
    infer_and_create_time_arrays_if_not_given,
    threshold_cdf_vals,
    year,
)
from ..variables import Variable, pr, tas
from ._debiaser import Debiaser

default_settings = {
    tas: {"distribution": scipy.stats.norm, "trend_preservation": "absolute"},
    pr: {
        "distribution": gen_PrecipitationGammaLeftCensoredModel(censoring_threshold=0.05 / 86400, censor_in_ppf=False),
        "trend_preservation": "relative",
        "censor_values_to_zero": True,
        "censoring_threshold": 0.05 / 86400,
    },
}


# Reference Cannon et al. 2015
@attrs.define
class QuantileDeltaMapping(Debiaser):
    """
    Implements Quantile Delta Mapping following Cannon et al. 2015.
    Let cm refer to climate model output, obs to observations and hist/future to whether the data was collected from the reference period or is part of future projections.
    The future climate projections :math:`x_{\\text{cm_fut}}` are adjusted in two steps: 1) they are bias corrected by quantile mapping and in the same time also detrended in all quantiles, 2) the trends in all quantiles -- as projected by the model -- are imposed again onto the bias corrected values.

    In step 1) values :math:`x_{\\text{cm_fut}} (t)` are first mapped onto:

    .. math:: x_{\\text{cm_fut, bc}} (t) := F^{-1}_{\\text{obs}}(\\hat F_{\\text{cm_fut}}^{(t)}(x_{\\text{cm_fut}}(t)))

    Here :math:`\\hat F_{\\text{cm_fut}}^{(t)}` is the empirical CDF of future climate model values in a window around t. :math:`F^{-1}_{\\text{obs}}` is the inverse CDF estimated by fitting a distribution to observations.

    In step 2) :math:`x_{\\text{cm_fut, bc}} (t)` is then adjusting by imposing the modeled trend in all quantiles onto the bias corrected values. If relative trends are to be preserved :math:`x_{\\text{cm_fut, bc}} (t)` is mapped as follows:

    .. math:: x_{\\text{cm_fut, bc}} (t) \\rightarrow x_{\\text{cm_fut, bc}} (t) \\cdot \\Delta_{\\text{cm}}^{\\text{rel}} (t) = x_{\\text{cm_fut, bc}} (t) \\cdot \\frac{x_{\\text{cm_fut}} (t)}{F^{-1}_{\\text{cm_hist}}(\\hat F_{\\text{cm_fut}}^{(t)}(x_{\\text{cm_fut}}))}

    and if absolute trends are to be preserved:

    .. math:: x_{\\text{cm_fut, bc}} (t) \\rightarrow x_{\\text{cm_fut, bc}} (t) + \\Delta_{\\text{cm}}^{\\text{abs}} (t) = x_{\\text{cm_fut, bc}} (t) + x_{\\text{cm_fut}} (t) - F^{-1}_{\\text{cm_hist}}(\\hat F_{\\text{cm_fut}}^{(t)} ( x_{\\text{cm_fut}}))

    Here :math:`F^{-1}_{\\text{cm_hist}}` is the inverse CDF estimated by fitting a distribution to the historical climate model run and :math:`\\hat F_{\\text{cm_fut}}^{(t)}` stands again for the empirical CDF fitted on a time window of future climate model values around t.

    Delta Quantile Mapping is approximately trend preserving in all quantiles because the absolute :math:`\\Delta_{\\text{cm}}^{\\text{abs}}` or relative change :math:`\\Delta_{\\text{cm}}^{\\text{rel}}` is calculated and applied for each quantile individually.


    Running window:

    - "running_window_over_year": controls whether the methodology and mapping is applied on a running window over the year to account for seasonality. "running_window_over_year_length" and "running_window_over_year_step_length" control the length (how many days are included in the running window) and step length (by how far the window is shifted and how many days inside are debiased) respectively.
    - "running_window_mode_over_years_of_cm_future" controls whether a running window is used to estimate the empirical CDF :math:`\\hat F_{\\text{cm_fut}}^{(t)}(x_{\\text{cm_fut}}(t))` and time-dependent quantiles or if this is done statically on the whole future climate model run. running_window_over_years_of_cm_future_length and running_window_over_years_of_cm_future_step_length control the length and step length of this window respectively. Estimation this information in a running window has the advantage of accounting for changes in trends.

    If both running windows are active then first the running window inside the year is used to account for seasonality. Values are chunked according to this one. Afterwards the running window over years is used and values are further split up. This is just a choice made for computational efficiency and the order of running window application/chunking does not matter.


    .. warning:: Currently only uneven sizes are allowed for window length and window step length. This allows symmetrical windows of the form [window_center - window length//2, window_center + window length//2] given an arbitrary window center. This affects both within year and over year window.


    **References**:

    - Cannon, A. J., Sobie, S. R., & Murdock, T. Q. (2015). Bias Correction of GCM Precipitation by Quantile Mapping: How Well Do Methods Preserve Changes in Quantiles and Extremes? In Journal of Climate (Vol. 28, Issue 17, pp. 6938–6959). American Meteorological Society. https://doi.org/10.1175/jcli-d-14-00754.1


    Attributes
    ----------
    distribution: Union[scipy.stats.rv_continuous, scipy.stats.rv_discrete, scipy.stats.rv_histogram, StatisticalModel]
        Distribution or statistical model used to compute the CDF F of observations and historical climate model values.
        Usually a distribution in scipy.stats.rv_continuous, but can also be an empirical distribution as given by scipy.stats.rv_histogram or a more complex statistical model as wrapped by the StatisticalModel class (see utils).
    trend_preservation: str
        One of ["absolute", "relative"]. If "absolute" then absolute trend preservation is used, if "relative" then relative trend preservation is used.

    censor_values_to_zero: bool
        Whether values below a censoring threhsold shall be censored to zero. Default: False. Only relevant for precipitation.
    censoring_threshold: float
        Threshold below which values shall be censored to zero if censor_values_to_zero = True. Relevant mainly for precipitation.
        If it is used (so censor_values_to_zero = True) one needs to make sure that the distribution fits to censored data, knows the correct censoring_threshold and assumes all observations under the specified censoring_threshold are zero/censored.
        If the standard for_precipitation and from_variable methods are used to construct the class this is ensured by default. However if this parameter is changed manually or own distributions for precipitation are specified problems can arise.

    running_window_mode_over_years_of_cm_future: bool
        Controls whether the methodology is applied on a running time window, running over the years of cm_fut to calculate time dependent quantiles in future climate model values.
    running_window_over_years_of_cm_future_length: int
        Length of the time window centered around t to calculate time dependent quantiles in future climate model values (default: 31 years). Only relevant if running_window_mode_over_years_of_cm_future = True.
    running_window_over_years_of_cm_future_step_length: int
        Step length of the time window centered around t to calculate time dependent quantiles in future climate model values (default: 1 year). Only relevant if running_window_mode_over_years_of_cm_future = True

    running_window_mode_within_year: bool
        Controls whether the methodology is applied in a running window over the year (default = True).
    running_window_within_year_length: int
        Length of the running window over the year in days (default: 91 days). Only relevant if running_window_over_year = True.
    running_window_within_year_step_length: int
        Step length of the running window over the year in days (default 31 days). Only relevant if running_window_over_year = True.

    variable: str
        Variable for which the debiasing is done. Default: "unknown".

    ecdf_method: str
        One of ["kernel_density", "linear_interpolation", "step_function"]. Method used to calculate the empirical CDF. Default: "linear_interpolation".
    cdf_threshold: Optional[float]
        Threshold for the CDF-values to round away from 0 and 1. Default: None. It is then set to 1 / (self.running_window_within_year_length * self.running_window_over_years_of_cm_future_length + 1)
    """

    distribution: Union[
        scipy.stats.rv_continuous, scipy.stats.rv_discrete, scipy.stats.rv_histogram, StatisticalModel
    ] = attrs.field(
        validator=attrs.validators.instance_of(
            (scipy.stats.rv_continuous, scipy.stats.rv_discrete, scipy.stats.rv_histogram, StatisticalModel)
        )
    )
    trend_preservation: str = attrs.field(validator=attrs.validators.in_(["absolute", "relative"]))

    # Relevant for precipitation
    censor_values_to_zero: bool = attrs.field(default=False, validator=attrs.validators.instance_of(bool))
    censoring_threshold: float = attrs.field(
        default=0.05 / 86400, validator=attrs.validators.instance_of(float), converter=float
    )

    # Running window over years
    running_window_mode_over_years_of_cm_future: bool = attrs.field(
        default=True, validator=attrs.validators.instance_of(bool)
    )
    running_window_over_years_of_cm_future_length: int = attrs.field(
        default=31, validator=[attrs.validators.instance_of(int), attrs.validators.gt(0)]
    )
    running_window_over_years_of_cm_future_step_length: int = attrs.field(
        default=1, validator=[attrs.validators.instance_of(int), attrs.validators.gt(0)]
    )

    # Running window within years
    running_window_mode_within_year: bool = attrs.field(default=True, validator=attrs.validators.instance_of(bool))
    running_window_within_year_length: int = attrs.field(
        default=91, validator=[attrs.validators.instance_of(int), attrs.validators.gt(0)]
    )
    running_window_within_year_step_length: int = attrs.field(
        default=31, validator=[attrs.validators.instance_of(int), attrs.validators.gt(0)]
    )

    variable: str = attrs.field(default="unknown", eq=False)

    # Calculation parameters
    ecdf_method: str = attrs.field(
        default="linear_interpolation",
        validator=attrs.validators.in_(["kernel_density", "linear_interpolation", "step_function"]),
    )
    cdf_threshold: Optional[float] = attrs.field(
        default=None, validator=attrs.validators.instance_of((float, type(None)))
    )

    def __attrs_post_init__(self):
        if self.running_window_mode_over_years_of_cm_future:
            self.running_window_over_years_of_cm_future = RunningWindowOverYears(
                window_length_in_years=self.running_window_over_years_of_cm_future_length,
                window_step_length_in_years=self.running_window_over_years_of_cm_future_step_length,
            )
        if self.running_window_mode_within_year:
            self.running_window_within_year = RunningWindowOverDaysOfYear(
                window_length_in_days=self.running_window_within_year_length,
                window_step_length_in_days=self.running_window_within_year_step_length,
            )
        if self.cdf_threshold is None:
            self.cdf_threshold = 1 / (
                self.running_window_within_year_length * self.running_window_over_years_of_cm_future_length + 1
            )

    @classmethod
    def from_variable(cls, variable: Union[str, Variable], **kwargs):
        if (variable == "pr" or variable == pr) and (censoring_threshold := kwargs.pop("censoring_threshold", None)):
            return QuantileDeltaMapping.for_precipitation(censoring_threshold, **kwargs)
        return super().from_variable(cls, variable, default_settings, **kwargs)

    @classmethod
    def for_precipitation(cls, censoring_threshold: float = 0.05 / 86400, **kwargs):
        """
        Instanciates the class to a precipitation-debiaser.

        Parameters
        ----------
        censoring_threshold: float
            The censoring-value under which precipitation amounts are assumed zero/censored.
        **kwargs:
            All other class attributes that shall be set and where the standard values shall be overwritten.

        """
        if distribution := kwargs.pop("distribution", None):
            warning(
                "If specifying an own precipitation distribution make sure that the .fit-methods fits to censored data and assumes all observations under the specified censoring_threshold are zero/censored."
            )
        else:
            distribution = gen_PrecipitationGammaLeftCensoredModel(
                censoring_threshold=censoring_threshold, censor_in_ppf=False
            )
        return super().from_variable(
            cls, "pr", default_settings, censoring_threshold=censoring_threshold, distribution=distribution, **kwargs
        )

    # ----- Helpers ----- #
    @staticmethod
    def _check_time_information_and_raise_error(obs, cm_hist, cm_future, time_obs, time_cm_hist, time_cm_future):
        if obs.size != time_obs.size or cm_hist.size != time_cm_hist.size or cm_future.size != time_cm_future.size:
            raise ValueError(
                """Dimensions of time information for one of time_obs, time_cm_hist, time_cm_future do not correspond to the dimensions of obs, cm_hist, cm_future. 
                Make sure that for each one of obs, cm_hist, cm_future time information is given for each value in the arrays."""
            )

    # ----- Main application functions ----- #

    def _apply_debiasing_steps(self, cm_future: np.ndarray, fit_obs: np.ndarray, fit_cm_hist: np.ndarray) -> np.ndarray:
        """
        Applies QuantileDeltaMapping at one location and returns the debiased timeseries.
        """

        tau_t = threshold_cdf_vals(
            ecdf(cm_future, cm_future, method=self.ecdf_method),
            cdf_threshold=self.cdf_threshold,
        )

        if self.trend_preservation == "absolute":
            bias_corrected_vals = (
                cm_future + self.distribution.ppf(tau_t, *fit_obs) - self.distribution.ppf(tau_t, *fit_cm_hist)
            )
        elif self.trend_preservation == "relative":
            bias_corrected_vals = (
                cm_future * self.distribution.ppf(tau_t, *fit_obs) / self.distribution.ppf(tau_t, *fit_cm_hist)
            )
        else:
            raise ValueError('self.trend_preservation needs to be one of ["absolute", "relative"]')

        if self.censor_values_to_zero:
            bias_corrected_vals[bias_corrected_vals < self.censoring_threshold] = 0

        return bias_corrected_vals

    def _get_obs_and_cm_hist_fits(self, obs: np.ndarray, cm_hist: np.ndarray):
        fit_obs = self.distribution.fit(obs)
        fit_cm_hist = self.distribution.fit(cm_hist)

        return fit_obs, fit_cm_hist

    def _apply_on_within_year_window(
        self, obs: np.ndarray, cm_hist: np.ndarray, cm_future: np.ndarray, years_cm_future: np.ndarray
    ):
        fit_obs, fit_cm_hist = self._get_obs_and_cm_hist_fits(obs, cm_hist)

        if self.running_window_mode_over_years_of_cm_future:

            debiased_cm_future = np.empty_like(cm_future)

            # Iteration over years of cm_future to account for trends
            for years_to_debias, years_in_window in self.running_window_over_years_of_cm_future.use(years_cm_future):

                mask_years_in_window = RunningWindowOverYears.get_if_in_chosen_years(years_cm_future, years_in_window)
                mask_years_to_debias = RunningWindowOverYears.get_if_in_chosen_years(years_cm_future, years_to_debias)
                mask_years_in_window_to_debias = RunningWindowOverYears.get_if_in_chosen_years(
                    years_cm_future[mask_years_in_window], years_to_debias
                )

                debiased_cm_future[mask_years_to_debias] = self._apply_debiasing_steps(
                    cm_future=cm_future[mask_years_in_window], fit_obs=fit_obs, fit_cm_hist=fit_cm_hist
                )[mask_years_in_window_to_debias]

            return debiased_cm_future

        else:
            return self._apply_debiasing_steps(cm_future=cm_future, fit_obs=fit_obs, fit_cm_hist=fit_cm_hist)

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
                    QuantileDeltaMapping runs without time-information for at least one of obs, cm_hist or cm_future.
                    This information is inferred, assuming the first observation is on a January 1st. Observations are chunked according to the assumed time information. 
                    This might lead to slight numerical differences to the run with time information, however the debiasing is not fundamentally changed.
                    """
            )
            time_obs, time_cm_hist, time_cm_future = infer_and_create_time_arrays_if_not_given(
                obs, cm_hist, cm_future, time_obs, time_cm_hist, time_cm_future
            )

        QuantileDeltaMapping._check_time_information_and_raise_error(
            obs, cm_hist, cm_future, time_obs, time_cm_hist, time_cm_future
        )

        years_cm_future = year(time_cm_future)

        if self.running_window_mode_within_year:
            days_of_year_obs = day_of_year(time_obs)
            days_of_year_cm_hist = day_of_year(time_cm_hist)
            days_of_year_cm_future = day_of_year(time_cm_future)

            debiased_cm_future = np.zeros_like(cm_future)  # TODO: replace by empty_like
            # Problem: not all cm_future values are filled!!!!

            # Iteration over year to account for seasonality
            for window_center, indices_bias_corrected_values in self.running_window_within_year.use(
                days_of_year_cm_future, years_cm_future
            ):

                indices_window_obs = self.running_window_within_year.get_indices_vals_in_window(
                    days_of_year_obs, window_center
                )
                indices_window_cm_hist = self.running_window_within_year.get_indices_vals_in_window(
                    days_of_year_cm_hist, window_center
                )
                indices_window_cm_future = self.running_window_within_year.get_indices_vals_in_window(
                    days_of_year_cm_future, window_center
                )

                debiased_cm_future[indices_bias_corrected_values] = self._apply_on_within_year_window(
                    obs=obs[indices_window_obs],
                    cm_hist=cm_hist[indices_window_cm_hist],
                    cm_future=cm_future[indices_window_cm_future],
                    years_cm_future=years_cm_future[indices_window_cm_future],
                )[np.in1d(indices_window_cm_future, indices_bias_corrected_values)]

            return debiased_cm_future

        else:
            return self._apply_on_within_year_window(
                obs=obs,
                cm_hist=cm_hist,
                cm_future=cm_future,
                years_cm_future=years_cm_future,
            )
