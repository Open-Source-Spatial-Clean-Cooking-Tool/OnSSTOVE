import sys
sys.path.append(r"C:\Users\camilorg\Box sync\OnSSTOVE")
import os

import numpy as np

from onsstove.onsstove import OnSSTOVE

# 1. Read the OnSSTOVE model
country = snakemake.params.country
print(f'[{country}] Reading model')
model = OnSSTOVE.read_model(snakemake.input.model)

# 2. Read the scenario data
print(f'[{country}] Scenario data')
path = snakemake.input.scenario_file
model.read_scenario_data(path, delimiter=',')
model.output_directory = snakemake.params.output_directory

# 3. Calculating benefits and costs of each technology and getting the max benefit technology for each cell
model.run(technologies=['Electricity', 'LPG', 'Biogas',
                        'Collected_Improved_Biomass', 'Collected_Traditional_Biomass'
                        ])

# 4. Printing the results
model.summary(inplace=True)

# 5. Saving data to raster files
# TODO: Update this to the ones in the nb
cmap = {"ICS": '#57365A', "LPG": '#6987B7', "Traditional biomass": '#673139', "Charcoal": '#B6195E',
        "Biogas": '#3BE2C5', "Biogas and ICS": "#F6029E",
        "Biogas and LPG": "#C021C0",  "Biogas and Traditional biomass": "#266AA6",
        "Biogas and Charcoal": "#3B05DF", "Biogas and Electricity": "#484673",
        "Electricity": '#D0DF53', "Electricity and ICS": "#4D7126",
        "Electricity and LPG": "#004D40", "Electricity and Traditional biomass": "#FFC107",
        "Electricity and Charcoal": "#1E88E5", "Electricity and Biogas": "#484673"}

labels = {"Biogas and Electricity": "Electricity and Biogas",
          'Collected Traditional Biomass': 'Traditional biomass',
          'Collected Improved Biomass': 'ICS'}

model.gdf['max_benefit_tech'] = model.gdf['max_benefit_tech'].str.replace('_', ' ')
model.gdf['max_benefit_tech'] = model.gdf['max_benefit_tech'].str.replace('Collected Traditional Biomass', 'Traditional biomass')
model.gdf['max_benefit_tech'] = model.gdf['max_benefit_tech'].str.replace('Collected Improved Biomass', 'ICS')
model.to_raster('max_benefit_tech', labels=labels, cmap=cmap)
model.to_raster('net_benefit_Electricity')
model.to_raster('net_benefit_LPG')
model.to_raster('net_benefit_Collected_Traditional_Biomass')
model.to_raster('net_benefit_Collected_Improved_Biomass')
model.to_raster('maximum_net_benefit')
# model.to_raster('investment_costs')

model.to_image('maximum_net_benefit', cmap='Spectral', cumulative_count=[0.01, 0.99],
               title=f'Maximum net benefit | {country}', dpi=600,
               rasterized=True)
model.to_image('max_benefit_tech', cmap=cmap, legend_position=(1, 0.9),
               title=f'Maximum benefit technology | {country}', dpi=600,
               labels=labels, legend=True, legend_title='Maximum benefit\ncooking technology', rasterized=True)

model.plot_split(cmap=cmap, labels=labels, save=True, height=1.5, width=2.5)

print(f'[{country}] Saving the results')

model.summary.to_csv(os.path.join(snakemake.params.output_directory, 'summary.csv'), index=False)
model.to_pickle('results.pkl')

