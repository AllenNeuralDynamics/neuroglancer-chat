what are the unique values in cluster_labels column?

can you give me all the Pvalb clusters?


## plotting
- sample 20 cells and scatter log_volume vs elongation



## Add annotation from query
Can you get the top log_volume in each cluster_label. include spatial coordinates. Then make a new annotation layer with a point for each cell. Call the layer "Clusters". Make it Green.


## ctl data
+ https://aind-neuroglancer-sauujisjxq-uw.a.run.app/#!s3://aind-open-data/HCR_785054-v1_2025-10-31_13-00-00/raw_data.json




## app testing
+ loaded ctl NG and got :Error: WebGL not supported.



 
# user cases
+ 1) given coreg what is happening(Qc/validation/)
    1) annotate all coreg cells; view them
    2) Spots for r4 to r5 on oregano round 5. 
    3) bounding box around the coreg volume. 

# next feature (11/3)

yes place it in a viewer controls card in the settings panel, keep open by default. while we are at it we can remove the opened: ng link from the settings panel it is redundant . please create a plan and then implement