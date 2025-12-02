what are the unique values in cluster_labels column?

can you give me all the Pvalb clusters?


## plotting
- sample 20 cells and scatter log_volume vs elongation

## basic annotation
please add a new annotation layer "a1" with a point at the current camera position.

## Add annotation from query
Can you get the top log_volume in each cluster_label. include spatial coordinates. Then make a new annotation layer with a point for each cell. Call the layer "Clusters". Make it Green.


## ctl data
+ https://aind-neuroglancer-sauujisjxq-uw.a.run.app/#!s3://aind-open-data/HCR_785054-v1_2025-10-31_13-00-00/raw_data.json


## sst spot count
In the csv, group_by cell_id and get the Sst cell with highest spot count

f.filter(pl.col('mixed_gene')=='Sst').group_by('cell_id').agg(pl.count('spot_id').alias('spot_count')).sort('spot_count', descending=True).head(1).select([pl.col('cell_id'), pl.col('spot_count')])

## spots for a cell
**prompt 0**
Can you set the LUT to 90-600 for all image layers (but not the Cck layer)?

**prompt**
og: Can you query the csv for the average cell_volume of mixed_gene column?
NLP: Prompt: Can you give me the average cell_volume of gene column from the coregistered table?

**plot**
Please make a scatter plot of dist and r columns for gene = Vip, from the coregistered cells table.

**prompt 1**
make a annotation layer "cell_spots"
query the csv for cell_id = 74330 and chan = 638, include spatial cols x y z
add annotation points for each location in query
(set viewer camera to the first spot location in the query)()

NLP: Cell 74330 has cool functional data! Please add two annotation layers, for genes Calb2 and Vip and plot the spots as annotations points. Spot colors, Calb1= red and Vip=Yellow

*prompt 2**
can you do that again, but only include spots with r > .6. make new layer "high_r" and make spots blue

**prompt 3**
+ make new layer "coreg_cells". make it purple.
+ For each cell_id in the file, sample one row (include x,y,z cols)
+ add a point annotation for each location to new layer

**plotting + query**
can query for cell_id = 74330 and plot scatter of x y cols for all rows?


Cell 74330 has cool functional data! Can you add and annotation layer, and plot the spots z y x locations for gene = Vip as annotations points.
Now add a new annotation layer for cell 74330 and gene=Calb2, plot the spots z y x locations. make it yellow

## batching annotation spots
Identify unique gene. then for cell 74330 make a new layer for each gene (name it for the gene), random color, and plot xyz locations of the spots.

batch:



## Use case
1) oregano with r4/r5 spots
+ csv: https://neuroglancer-demo.appspot.com/#!s3://aind-open-data/HCR_767018_2025-09-18_13-00-00_processed_2025-09-20_22-57-09/fused_ng.json

 
# user cases
+ 1) given coreg what is happening(Qc/validation/)
    1) annotate all coreg cells; view them
    2) Spots for r4 to r5 on oregano round 5. 
    3) bounding box around the coreg volume. 




# next feature (11/3)

yes place it in a viewer controls card in the settings panel, keep open by default. while we are at it we can remove the opened: ng link from the settings panel it is redundant . please create a plan and then implement

