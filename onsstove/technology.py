import os
import geopandas as gpd
import re
import pandas as pd
import numpy as np
import datetime
from math import exp
from rasterstats import zonal_stats
import rasterio

from .raster import *
from .layer import *
from .raster import interpolate, rasterize


class Technology:
    """
    Standard technology class.
    """

    def __init__(self,
                 name=None,
                 carbon_intensity=0,
                 energy_content=0,
                 tech_life=0,  # in years
                 inv_cost=0,  # in USD
                 infra_cost=0,  # cost of additional infrastructure
                 fuel_cost=0,
                 time_of_cooking=0,
                 om_cost=0,  # percentage of investement cost
                 efficiency=0,  # ratio
                 pm25=0,
                 is_base=False,
                 transport_cost=0):  # 24-h PM2.5 concentration

        self.name = name
        self.carbon_intensity = carbon_intensity
        self.energy_content = energy_content
        self.tech_life = tech_life
        self.fuel_cost = fuel_cost
        self.inv_cost = inv_cost
        self.infra_cost = infra_cost
        self.om_cost = om_cost
        self.time_of_cooking = time_of_cooking
        self.efficiency = efficiency
        self.pm25 = pm25
        self.time_of_collection = None
        self.fuel_use = None
        self.is_base = is_base
        self.transport_cost = transport_cost

    def __setitem__(self, idx, value):
        if idx == 'name':
            self.name = value
        elif idx == 'energy_content':
            self.energy_content = value
        elif idx == 'carbon_intensity':
            self.carbon_intensity = value
        elif idx == 'fuel_cost':
            self.fuel_cost = value
        elif idx == 'tech_life':
            self.tech_life = value
        elif idx == 'inv_cost':
            self.inv_cost = value
        elif idx == 'infra_cost':
            self.infra_cost = value
        elif idx == 'om_cost':
            self.om_cost = value
        elif idx == 'time_of_cooking':
            self.time_of_cooking = value
        elif idx == 'efficiency':
            self.efficiency = value
        elif idx == 'pm25':
            self.pm25 = value
        elif idx == 'time_of_collection':
            self.time_of_collection = value
        elif idx == 'fuel_use':
            self.fuel_use = value
        elif idx == 'is_base':
            self.is_base = value
        else:
            raise KeyError(idx)

    def relative_risk(self):
        if self.pm25 < 7.298:
            rr_alri = 1
        else:
            rr_alri = 1 + 2.383 * (1 - exp(-0.004 * (self.pm25 - 7.298) ** 1.193))

        if self.pm25 < 7.337:
            rr_copd = 1
        else:
            rr_copd = 1 + 22.485 * (1 - exp(-0.001 * (self.pm25 - 7.337) ** 0.694))

        if self.pm25 < 7.505:
            rr_ihd = 1
        else:
            rr_ihd = 1 + 2.538 * (1 - exp(-0.081 * (self.pm25 - 7.505) ** 0.466))

        if self.pm25 < 7.345:
            rr_lc = 1
        else:
            rr_lc = 1 + 152.496 * (1 - exp(-0.000167 * (self.pm25 - 7.345) ** 0.76))

        return rr_alri, rr_copd, rr_ihd, rr_lc

    def paf(self, rr, sfu):

        paf = (sfu * (rr - 1)) / (sfu * (rr - 1) + 1)

        return paf

    @staticmethod
    def discount_factor(specs_file):
        '''

        :param self:
        :param specs_file: social specs file
        :return: discount factor to be used for all costs in the net benefit fucntion and the years of analysis
        '''
        if specs_file["Start_year"] == specs_file["End_year"]:
            proj_life = 1
        else:
            proj_life = specs_file["End_year"] - specs_file["Start_year"]

        year = np.arange(proj_life)

        discount_factor = (1 + specs_file["Discount_rate_tech"]) ** year

        return discount_factor, proj_life

    def carb(self, specs_file, gdf):
        self.carbon = (3.64 * specs_file["Meals_per_day"] * 365 * self.carbon_intensity) / (self.efficiency * 1000)

    def carbon_emissions(self, specs_file, gdf, carb_base_fuel):
        self.carb(specs_file, gdf)
        proj_life = specs_file['End_year'] - specs_file['Start_year']
        carbon = specs_file["Cost of carbon emissions"] * (carb_base_fuel - self.carbon) / 1000 / (
                    1 + specs_file["Discount_rate"]) ** (proj_life)

        self.decreased_carbon_emissions = carb_base_fuel - self.carbon
        self.decreased_carbon_costs = carbon

    def mortality(self, specs_file, gdf, paf_0_alri, paf_0_copd, paf_0_lc, paf_0_ihd):
        """
        Calculates mortality rate per fuel

        Returns
        ----------
        Monetary mortality for each stove in urban and rural settings
        """
        rr_alri, rr_copd, rr_ihd, rr_lc = self.relative_risk()

        paf_alri = self.paf(rr_alri, 1 - specs_file['clean_cooking_access'])
        paf_copd = self.paf(rr_copd, 1 - specs_file['clean_cooking_access'])
        paf_ihd = self.paf(rr_ihd, 1 - specs_file['clean_cooking_access'])
        paf_lc = self.paf(rr_lc, 1 - specs_file['clean_cooking_access'])

        mort_alri = gdf["Calibrated_pop"].sum() * (paf_0_alri - paf_alri) * (specs_file["Mort_ALRI"] / 100000)
        mort_copd = gdf["Calibrated_pop"].sum() * (paf_0_copd - paf_copd) * (specs_file["Mort_COPD"] / 100000)
        mort_ihd = gdf["Calibrated_pop"].sum() * (paf_0_ihd - paf_ihd) * (specs_file["Mort_IHD"] / 100000)
        mort_lc = gdf["Calibrated_pop"].sum() * (paf_0_lc - paf_lc) * (specs_file["Mort_LC"] / 100000)

        cl_copd = {1: 0.3, 2: 0.2, 3: 0.17, 4: 0.17, 5: 0.16}
        cl_alri = {1: 0.7, 2: 0.1, 3: 0.07, 4: 0.07, 5: 0.06}
        cl_lc = {1: 0.2, 2: 0.1, 3: 0.24, 4: 0.23, 5: 0.23}
        cl_ihd = {1: 0.2, 2: 0.1, 3: 0.24, 4: 0.23, 5: 0.23}

        i = 1
        mort_vector = []
        while i < 6:
            mortality_alri = cl_alri[i] * specs_file["VSL"] * mort_alri / (1 + specs_file["Discount_rate"]) ** (i - 1)
            mortality_copd = cl_copd[i] * specs_file["VSL"] * mort_copd / (
                    1 + specs_file["Discount_rate"]) ** (i - 1)
            mortality_lc = cl_lc[i] * specs_file["VSL"] * mort_lc / (
                    1 + specs_file["Discount_rate"]) ** (i - 1)
            mortality_ihd = cl_ihd[i] * specs_file["VSL"] * mort_ihd / (
                    1 + specs_file["Discount_rate"]) ** (i - 1)

            mort_total = (1 + specs_file["Health_spillovers_parameter"]) * (
                    mortality_alri + mortality_copd + mortality_lc + mortality_ihd)

            mort_vector.append(mort_total)

            i += 1

        mortality = np.sum(mort_vector)

        #  Distributed mortality per household
        self.distributed_mortality = gdf["Calibrated_pop"] / (gdf["Calibrated_pop"].sum() * gdf['Households']) * mortality
        #  Total deaths avoided
        self.deaths_avoided = (mort_alri + mort_copd + mort_lc + mort_ihd) * (gdf["Calibrated_pop"] / (gdf["Calibrated_pop"].sum() * gdf['Households']))

    def morbidity(self, specs_file, gdf, paf_0_alri, paf_0_copd, paf_0_lc, paf_0_ihd):
        """
        Calculates morbidity rate per fuel

        Returns
        ----------
        Monetary morbidity for each stove in urban and rural settings
        """
        rr_alri, rr_copd, rr_ihd, rr_lc = self.relative_risk()

        paf_alri = self.paf(rr_alri, 1 - specs_file['clean_cooking_access'])
        paf_copd = self.paf(rr_copd, 1 - specs_file['clean_cooking_access'])
        paf_ihd = self.paf(rr_ihd, 1 - specs_file['clean_cooking_access'])
        paf_lc = self.paf(rr_lc, 1 - specs_file['clean_cooking_access'])

        morb_alri = gdf["Calibrated_pop"].sum() * (paf_0_alri - paf_alri) * (specs_file["Morb_ALRI"] / 100000)
        morb_copd = gdf["Calibrated_pop"].sum() * (paf_0_copd - paf_copd) * (specs_file["Morb_COPD"] / 100000)
        morb_ihd = gdf["Calibrated_pop"].sum() * (paf_0_ihd - paf_ihd) * (specs_file["Morb_IHD"] / 100000)
        morb_lc = gdf["Calibrated_pop"].sum() * (paf_0_lc - paf_lc) * (specs_file["Morb_LC"] / 100000)

        cl_copd = {1: 0.3, 2: 0.2, 3: 0.17, 4: 0.17, 5: 0.16}
        cl_alri = {1: 0.7, 2: 0.1, 3: 0.07, 4: 0.07, 5: 0.06}
        cl_lc = {1: 0.2, 2: 0.1, 3: 0.24, 4: 0.23, 5: 0.23}
        cl_ihd = {1: 0.2, 2: 0.1, 3: 0.24, 4: 0.23, 5: 0.23}

        i = 1
        morb_vector = []
        while i < 6:
            morbidity_alri = cl_alri[i] * specs_file["COI_ALRI"] * morb_alri / (1 + specs_file["Discount_rate"]) ** (
                    i - 1)
            morbidity_copd = cl_copd[i] * specs_file["COI_COPD"] * morb_copd / (1 + specs_file["Discount_rate"]) ** (
                    i - 1)
            morbidity_lc = cl_lc[i] * specs_file["COI_LC"] * morb_lc / (1 + specs_file["Discount_rate"]) ** (i - 1)
            morbidity_ihd = cl_ihd[i] * specs_file["COI_IHD"] * morb_ihd / (1 + specs_file["Discount_rate"]) ** (i - 1)

            morb_total = (1 + specs_file["Health_spillovers_parameter"]) * (
                    morbidity_alri + morbidity_copd + morbidity_lc + morbidity_ihd)

            morb_vector.append(morb_total)

            i += 1

        morbidity = np.sum(morb_vector)

        self.distributed_morbidity = gdf["Calibrated_pop"] / (gdf["Calibrated_pop"].sum() * gdf['Households']) * morbidity
        self.cases_avoided = (morb_alri + morb_copd + morb_lc + morb_ihd) * (gdf["Calibrated_pop"] / (gdf["Calibrated_pop"].sum() * gdf['Households']))

    def salvage(self, gdf, specs_file):
        """
        Calculates discounted salvage cost assuming straight-line depreciation
        Returns
        ----------
        discounted salvage cost
        """
        discount_rate, proj_life = self.discount_factor(specs_file)
        salvage = np.zeros(proj_life)
        used_life = proj_life % self.tech_life

        salvage[-1] = self.inv_cost * (1 - used_life / self.tech_life)

        discounted_salvage = salvage.sum() / discount_rate

        self.discounted_salvage_cost = discounted_salvage

    def discounted_om(self, gdf, specs_file):
        """
        Calls discount_factor function and creates discounted OM costs.
        Returns
        ----------
        discountedOM costs for each stove during the project lifetime
        """
        discount_rate, proj_life = self.discount_factor(specs_file)
        operation_and_maintenance = self.om_cost * np.ones(proj_life) * self.inv_cost
        operation_and_maintenance[0] = 0

        i = self.tech_life
        while i < proj_life:
            operation_and_maintenance[i] = 0
            i = i + self.tech_life

        discounted_om_cost = operation_and_maintenance.sum() / discount_rate

        self.discounted_om_costs = discounted_om_cost

    def discounted_inv(self, gdf, specs_file):
        """
        Calls discount_factor function and creates discounted investment cost. Uses proj_life and tech_life to determine
        number of necessary re-investments

        Returns
        ----------
        discounted investment cost for each stove during the project lifetime
        """
        discount_rate, proj_life = self.discount_factor(specs_file)

        investments = np.zeros(proj_life)
        investments[0] = self.inv_cost

        i = self.tech_life
        while i < proj_life:
            investments[i] = self.inv_cost
            i = i + self.tech_life

        discounted_investments = investments / discount_rate

        self.discounted_investments = discounted_investments.sum()

    def discounted_meals(self, gdf, specs_file):
        discount_rate, proj_life = self.discount_factor(specs_file)

        energy = specs_file["Meals_per_day"] * 365 * 3.64 / self.efficiency
        gdf["needed_energy"] = specs_file["Meals_per_day"] * 365 * 3.64 / self.efficiency

        energy_needed = energy * np.ones(proj_life)

        self.discounted_energy = (energy_needed / discount_rate)

    def discount_fuel_cost(self, gdf, specs_file, rows=None, cols=None):

        discount_rate, proj_life = self.discount_factor(specs_file)

        energy = specs_file["Meals_per_day"] * 365 * 3.64 / self.efficiency

        cost = (energy * self.fuel_cost / self.energy_content + self.transport_cost) * np.ones(gdf.shape[0])

        fuel_cost = [np.ones(proj_life) * x for x in cost]

        fuel_cost_discounted = np.array([sum(x / discount_rate) for x in fuel_cost])

        self.discounted_fuel_cost = pd.Series(fuel_cost_discounted, index=gdf.index)

    def total_time(self, onstove):
        self.total_time_yr = self.time_of_cooking * 365

    def time_saved(self, onstove):
        if self.is_base:
            self.total_time_saved = 0
            self.time_value = 0
        else:
            proj_life = onstove.specs['End_year'] - onstove.specs['Start_year']
            self.total_time(onstove)
            self.total_time_saved = onstove.base_fuel.total_time_yr - self.total_time_yr  # time saved per household
            # time value of time saved per sq km
            self.time_value = self.total_time_saved * onstove.gdf["value_of_time"] / (1 + onstove.specs["Discount_rate"]) ** (proj_life)

    def total_costs(self):

        self.costs = (
                    self.discounted_fuel_cost + self.discounted_investments + self.discounted_om_costs - self.discounted_salvage_cost)  # / self.discounted_energy

    def net_benefit(self, gdf):
        self.total_costs()
        self.benefits = self.distributed_morbidity + self.distributed_mortality + self.decreased_carbon_costs + self.time_value
        gdf["costs_{}".format(self.name)] = self.costs
        gdf["benefits_{}".format(self.name)] = self.benefits
        gdf["net_benefit_{}".format(self.name)] = self.benefits - self.costs


class LPG(Technology):
    """
    LPG technology class. Inherits all functionality from the standard
    Technology class
    """

    def __init__(self,
                 name=None,
                 carbon_intensity=0,
                 energy_content=0,
                 tech_life=0,  # in years
                 inv_cost=0,  # in USD
                 infra_cost=0,  # cost of additional infrastructure
                 fuel_cost=0,
                 time_of_cooking=0,
                 om_cost=0,  # percentage of investement cost
                 efficiency=0,  # ratio
                 pm25=0,
                 travel_time=None,
                 truck_capacity=2000,
                 diesel_price=0.88,
                 diesel_per_hour=14,
                 lpg_path=None,
                 friction_path=None):
        super().__init__(name, carbon_intensity, energy_content, tech_life,
                         inv_cost, infra_cost, fuel_cost, time_of_cooking,
                         om_cost, efficiency, pm25)
        self.travel_time = travel_time
        self.truck_capacity = truck_capacity
        self.diesel_price = diesel_price
        self.diesel_per_hour = diesel_per_hour
        self.transport_cost = None
        self.lpg_path = lpg_path
        self.friction_path = friction_path

    def add_travel_time(self, population, out_path):
        lpg = VectorLayer(self.name, 'LPG_points', layer_path=self.lpg_path)
        friction = RasterLayer(self.name, 'friction', layer_path=self.friction_path, resample='average')

        os.makedirs(os.path.join(out_path, self.name, 'LPG_points'), exist_ok=True)
        lpg.reproject(population.meta['crs'], os.path.join(out_path, self.name, 'LPG_points'))
        friction.align(population.path, os.path.join(out_path, self.name, 'friction'))

        lpg.add_friction_raster(friction)
        lpg.travel_time(os.path.join(out_path, self.name))
        interpolate(lpg.distance_raster.path)
        self.travel_time = 2 * lpg.distance_raster.layer

    def transportation_cost(self, specs_file, gdf, rows, cols):
        """The cost of transporting LPG. See https://iopscience.iop.org/article/10.1088/1748-9326/6/3/034002/pdf for the formula

        Transportation cost = (2 * diesel consumption per h * national diesel price * travel time)/transported LPG

        Total cost = (LPG cost + Transportation cost)/efficiency of LPG stoves


        Each truck is assumed to transport 2,000 kg LPG
        (3.5 MT truck https://www.wlpga.org/wp-content/uploads/2019/09/2019-Guide-to-Good-Industry-Practices-for-LPG-Cylinders-in-the-
        Distribution-Channel.pdf)
        National diesel price in Nepal is assumed to be 0.88 USD/l
        Diesel consumption per h is assumed to be 14 l/h (14 l/100km)
        (https://www.iea.org/reports/fuel-consumption-of-cars-and-vans)
        LPG cost in Nepal is assumed to be 19 USD per cylinder (1.34 USD/kg)
        LPG stove efficiency is assumed to be 60%

        :param param1:  travel_time_raster
                        Hour to travel between each point and the startpoints as array
        :returns:       The cost of LPG in each cell per kg
        """
        transport_cost = (self.diesel_per_hour * self.diesel_price * self.travel_time) / self.truck_capacity
        kg_yr = (specs_file["Meals_per_day"] * 365 * 3.64) / (
                    self.efficiency * self.energy_content)  # energy content in MJ/kg
        transport_cost = transport_cost * kg_yr
        self.transport_cost = pd.Series(transport_cost[rows, cols], index=gdf.index)

    def discount_fuel_cost(self, gdf, specs_file, rows=None, cols=None):
        self.transportation_cost(specs_file, gdf, rows, cols)
        super().discount_fuel_cost(gdf, specs_file)


class Biomass(Technology):
    """
    LPG technology class. Inherits all functionality from the standard
    Technology class
    """

    def __init__(self,
                 name=None,
                 carbon_intensity=0,
                 energy_content=0,
                 tech_life=0,  # in years
                 inv_cost=0,  # in USD
                 infra_cost=0,  # cost of additional infrastructure
                 fuel_cost=0,
                 time_of_cooking=0,
                 om_cost=0,  # percentage of investement cost
                 efficiency=0,  # ratio
                 pm25=0,
                 forest_path=None,
                 friction_path=None,
                 travel_time=None):
        super().__init__(name, carbon_intensity, energy_content, tech_life,
                         inv_cost, infra_cost, fuel_cost, time_of_cooking,
                         om_cost, efficiency, pm25)
        self.travel_time = travel_time
        self.forest_path = forest_path
        self.friction_path = friction_path

    def transportation_time(self, friction_path, forest_path, onstove):
        forest = RasterLayer(self.name, 'forest', layer_path=forest_path, resample='mode')
        friction = RasterLayer(self.name, 'friction', layer_path=friction_path, resample='average')

        forest.align(onstove.base_layer.path, os.path.join(onstove.output_directory, self.name, 'Forest_points'))
        friction.align(onstove.base_layer.path, os.path.join(onstove.output_directory, self.name, 'friction'))

        forest.add_friction_raster(friction)
        forest.travel_time(os.path.join(onstove.output_directory, self.name))

        self.travel_time = 2 * pd.Series(forest.distance_raster.layer[onstove.rows, onstove.cols],
                                         index=onstove.gdf.index)

    def total_time(self, onstove):
        self.transportation_time(self.friction_path, self.forest_path, onstove)
        self.total_time_yr = self.time_of_cooking * onstove.specs['Meals_per_day'] * 365 + (
                self.travel_time + self.time_of_collection) * 52 * 2


class Electricity(Technology):
    """
    LPG technology class. Inherits all functionality from the standard
    Technology class
    """

    def __init__(self,
                 name=None,
                 carbon_intensity=0,
                 energy_content=0,
                 tech_life=0,  # in years
                 inv_cost=0,  # in USD
                 infra_cost=0,  # cost of additional infrastructure
                 fuel_cost=0,
                 time_of_cooking=0,
                 om_cost=0,  # percentage of investement cost
                 efficiency=0,  # ratio
                 pm25=0):
        super().__init__(name, carbon_intensity, energy_content, tech_life,
                         inv_cost, infra_cost, fuel_cost, time_of_cooking,
                         om_cost, efficiency, pm25)
        # Carbon intensity of fossil fuel plants in kg/GWh
        self.generation = {}
        self.carbon_intensities = {'coal': 0.090374363, 'natural_gas': 0.050300655,
                                   'crude_oil': 0.070650288, 'heavy_fuel_oil': 0.074687989,
                                   'oil': 0.072669139,'diesel': 0.069332823,
                                   'still_gas': 0.060849859, 'flared_natural_gas': 0.051855075,
                                   'waste': 0.010736111, 'biofuels_waste': 0.010736111,
                                   'nuclear': 0, 'hydro': 0, 'wind': 0,
                                   'solar': 0, 'other': 0}

    def __setitem__(self, idx, value):
        if 'generation' in idx:
            self.generation[idx.lower().replace('generation_', '')] = value
        elif 'carbon_intensity' in idx:
            self.carbon_intensities[idx.lower().replace('carbon_intensity_', '')] = value
        else:
            super().__setitem__(idx, value)

    def infrastructure_cost(self):
        pass

    def get_carbon_intensity(self):
        grid_emissions = sum([gen * self.carbon_intensities[fuel] for fuel, gen in self.generation.items()])
        grid_generation = sum(self.generation.values())
        self.carbon_intensity = grid_emissions / grid_generation * 1000  # to convert from Mton/PJ to kg/GJ

    def carb(self, specs_file, gdf):
        self.get_carbon_intensity()
        super().carb(specs_file, gdf)

    def net_benefit(self, gdf):
        super().net_benefit(gdf)
        gdf.loc[gdf['Current_elec'] == 0, "net_benefit_{}".format(self.name)] = np.nan


class Biogas(Technology):
    """
    LPG technology class. Inherits all functionality from the standard
    Technology class
    """

    def __init__(self,
                 name=None,
                 carbon_intensity=0,
                 energy_content=0,
                 tech_life=0,  # in years
                 inv_cost=0,  # in USD
                 infra_cost=0,  # cost of additional infrastructure
                 fuel_cost=0,
                 time_of_cooking=0,
                 om_cost=0,  # percentage of investement cost
                 efficiency=0,  # ratio
                 pm25=0):
        super().__init__(name, carbon_intensity, energy_content, tech_life,
                         inv_cost, infra_cost, fuel_cost, time_of_cooking,
                         om_cost, efficiency, pm25)

    def available_biogas(self, model):

        from_cattle = model.gdf["Cattles"] * 12 * 0.15 * 0.8 * 305
        from_buffalo = model.gdf["Buffaloes"] * 14 * 0.2 * 0.75 * 305
        from_sheep = model.gdf["Sheeps"] * 0.7 * 0.25 * 0.8 * 452
        from_goat = model.gdf["Goats"] * 0.6 * 0.3 * 0.85 * 450
        from_pig = model.gdf["Pigs"] * 5 * 0.75 * 0.14 * 470
        from_poultry = model.gdf["Poultry"] * 0.12 * 0.25 * 0.75 * 450

        model.gdf["yearly_cubic_meter_biogas"] = (from_cattle + from_buffalo + from_goat + from_pig + from_poultry + \
                                          from_sheep) * 0.365

        del model.gdf["Cattles"]
        del model.gdf["Buffaloes"]
        del model.gdf["Sheeps"]
        del model.gdf["Goats"]
        del model.gdf["Pigs"]
        del model.gdf["Poultry"]

    def available_energy(self, model, data):

        model.gdf.to_crs(4326, inplace = True)
        model.raster_to_dataframe(data, name = "Temperature")
        model.gdf.to_crs(model.project_crs, inplace = True)

        model.gdf.loc[model.gdf["Temperature"] < 10, "potential_households"] = 0
        model.gdf.loc[(model.gdf["IsUrban"] > 20), "potential_households"] = 0

        model.gdf.loc[(model.gdf["Temperature"] < 20) & (model.gdf["Temperature"] >= 10), "potential_households"] = model.gdf["potential_households"]/7.2
        model.gdf.loc[(model.gdf["Temperature"] >= 20),"potential_households"] = model.gdf["yearly_cubic_meter_biogas"]/6


        model.gdf["available_biogas_energy"] = model.gdf["yearly_cubic_meter_biogas"] * self.energy_content

    def recalibrate_livestock(self, model, admin, buffaloes, cattles, poultry, goats, pigs, sheeps):

        paths = {
            'Buffaloes': buffaloes,
            'Cattles': cattles,
            'Poultry': poultry,
            'Goats': goats,
            'Pigs': pigs,
            'Sheeps': sheeps}

        for name, path in paths.items():
            folder = f'{model.output_directory}/livestock/{name}'
            os.makedirs(folder, exist_ok=True)

            layer = RasterLayer('livestock', name, layer_path=path, resample='nearest')
            layer.mask(admin, folder)
            admin_zones = zonal_stats(admin, path, stats='sum', prefix='orig_', geojson_out=True,
                                all_touched=False)

            geostats = gpd.GeoDataFrame.from_features(admin_zones)

            geostats.crs = 4326
            geostats.to_crs(model.project_crs, inplace=True)
            layer.reproject(model.project_crs, output_path=folder, cell_width=1000,
                            cell_height=1000)

            admin_zones = zonal_stats(geostats, folder + r"/" + name + " - reprojected.tif", stats='sum', prefix='r_',
                                geojson_out=True,
                                all_touched=False)

            geostats = gpd.GeoDataFrame.from_features(admin_zones)

            geostats["ratio"] = geostats['orig_sum'] / geostats['r_sum']

            admin_image, admin_out_meta = rasterize(geostats, folder + r'/' + name + ' - reprojected.tif',
                                                    outpul_file=None,
                                                    value='ratio', nodata=-9999, compression='NONE', all_touched=True,
                                                    save=False, dtype=rasterio.float64)

            with rasterio.open(folder + r'/' + name + ' - reprojected.tif') as src:
                band = src.read(1)
                new_band = band * admin_image

            with rasterio.open(folder + r'/final_' + name + '.tif', 'w', **admin_out_meta) as dst:
                dst.write(new_band, 1)

            model.raster_to_dataframe(folder + r'/final_' + name + '.tif', name=name, method='sample')
            model.gdf[name] = model.gdf[name].fillna(0)
