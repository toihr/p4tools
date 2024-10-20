# AUTOGENERATED! DO NOT EDIT! File to edit: ../../notebooks/05_production.catalog.ipynb.

# %% auto 0
__all__ = ['LOGGER', 'execute_in_parallel', 'fan_id_generator', 'blotch_id_generator', 'get_L1A_paths', 'cluster_obsid',
           'fnotch_obsid', 'fnotch_obsid_parallel', 'cluster_obsid_parallel', 'add_marking_ids', 'create_roi_file',
           'ReleaseManager', 'read_csvfiles_into_lists_of_frames']

# %% ../../notebooks/05_production.catalog.ipynb 2
# other imports
from tqdm.auto import tqdm
import pandas as pd
import logging
import itertools
from planetarypy.pds.apps import get_index
import string
from dask import delayed, compute
import numpy as np

# p4tools package imports
import p4tools.production.io as io
import p4tools.production.metadata as p4meta
from .projection import XY2LATLON, P4Mosaic, TileCalculator, create_RED45_mosaic


#typing imports
from collections.abc import Iterable,Callable
from typing import Any, Generator
from logging import Logger
from pandas import DataFrame

# %% ../../notebooks/05_production.catalog.ipynb 3
#starting the logger
LOGGER: Logger = logging.getLogger(__name__)

# %% ../../notebooks/05_production.catalog.ipynb 4
def execute_in_parallel(func : Callable, iterable : Iterable):
    """This function is used to execute a function in paralle over a list-like or iterable using the power of Dask's lazy compute.

    Parameters
    ----------
    func : Callable 
        The function that is to be parallel computed over the iterable does not need to accept a
    iterable : Iterable
        The Iterable over which we want to execute the function for each of the elements in the iterable 

    Returns
    -------
    List
        The results of the function reduced over the Iterable
    """
    lazys = []
    for item in iterable:
        lazys.append(delayed(func)(item))
    return compute(*lazys)

# %% ../../notebooks/05_production.catalog.ipynb 5
from typing import Any, Generator


def fan_id_generator() -> Generator[str, Any, None]:
    """Generatir for the IDs to number the fans

    Yields
    ------
    Generator[str, Any, None]
        ID generator
    """
    for newid in itertools.product(string.digits + "abcdef", repeat=6):
        yield "F" + "".join(newid)


def blotch_id_generator() -> Generator[str, Any, None]:
    """Generator to yield the IDs to number the blotches

    Yields
    ------
    Generator[str, Any, None]
        ID generator
    """
    for newid in itertools.product(string.digits + "abcdef", repeat=6):
        yield "B" + "".join(newid)


def get_L1A_paths(obsid, savefolder):
    """
    Retrieve L1A observation paths for a given observation ID.
    Parameters
    ----------
    obsid : str
        The observation ID for which to retrieve the paths.
    savefolder : str
        The directory path where the data is stored.
    Returns
    -------
    list
        A list of paths corresponding to the L1A observation data.
    """
    pm = io.PathManager(obsid=obsid, datapath=savefolder)
    paths = pm.get_obsid_paths("L1A")
    return paths

# %% ../../notebooks/05_production.catalog.ipynb 6
def cluster_obsid(obsid=None, savedir=None, imgid=None, dbname=None):
    """Cluster all image_ids for given obsid (=image_name).

    Parameters
    ----------
    obsid : str
        HiRISE obsid (= Planet four image_name)
    savedir : str or pathlib.Path
        Top directory path where the catalog will be stored. Will create folder if it
        does not exist yet.
    imgid : str, optional
        Convenience parameter: If `obsid` is not given and therefore is None, this `image_id` can
        be used to receive the respective `obsid` from the TileID class.
    """
    # import here to support parallel execution
    from p4tools.production import markings, dbscan
    
    # parameter checks
    if obsid is None and imgid is not None:
        obsid = markings.TileID(imgid).image_name
    elif obsid is None and imgid is None:
        raise ValueError("Provide either obsid or imgid.")

    # cluster
    dbscanner = dbscan.DBScanner(savedir=savedir, dbname=dbname)
    dbscanner.cluster_image_name(obsid)
    return obsid

# %% ../../notebooks/05_production.catalog.ipynb 7
def fnotch_obsid(obsid=None, savedir=None, fnotch_via_obsid=False, imgid=None):
    """Perform fnotching on HiRISE images based on observation ID or image ID.

    Parameters
    ----------
    obsid : str, optional
        The observation ID to be processed.
    savedir : str, optional
        The directory where the results will be saved.
    fnotch_via_obsid : bool, optional
        Switch to control if fnotching happens per observation ID (obsid) or per image ID.
        If True, fnotching is done per observation ID. If False, fnotching is done per image ID.
    imgid : str, optional
        The image ID to be processed. This parameter is currently not used in the function.

    Returns
    -------
    str
        The observation ID that was processed.
    """
    from p4tools.production import fnotching

    # fnotching / combining ambiguous cluster results
    # fnotch across all the HiRISE image
    # does not work yet correctly! Needs to scale for n_classifications
    if fnotch_via_obsid is True:
        fnotching.fnotch_obsid(obsid, savedir=savedir)
        fnotching.apply_cut_obsid(obsid, savedir=savedir)
    else:
        # default case: Fnotch for each image_id separately.
        fnotching.fnotch_image_ids(obsid, savedir=savedir)
        fnotching.apply_cut(obsid, savedir=savedir)
    return obsid


def fnotch_obsid_parallel(obsids : list[str], savedir : str):
    """Applies the fnotching for multiple obsid's in parallel

    Parameters
    ----------
    obsids : list[str]
        List of the Obsids to fnotch
    savedir : str
        the directory path where to save
    """
    lazys = []
    for obsid in obsids:
        lazys.append(delayed(fnotch_obsid)(obsid, savedir))
    return compute(*lazys)


def cluster_obsid_parallel(obsids : list[str], savedir : str, dbname : str):
    """Apply the Clustering Algorithm for multiple obsids in parallel.

    Parameters
    ----------
    obsids : list[str]
        List of the obsids to cluster
    savedir : str
        path to the save directory whihc will save the clustering results
    dbname : str
        The databasename 
    """
    lazys = []
    for obsid in obsids:
        lazys.append(delayed(cluster_obsid)(obsid, savedir, dbname=dbname))
    return compute(*lazys)



# %% ../../notebooks/05_production.catalog.ipynb 8
def add_marking_ids(path, fan_id, blotch_id):
    """Add marking_ids for catalog to cluster results.

    Parameters
    ----------
    path : str, pathlib.Path
        Path to L1A image_id clustering result directory
    fan_id, blotch_id : generator
        Generator for marking_id
    """
    image_id = path.parent.name
    for kind, id_ in zip(["fans", "blotches"], [fan_id, blotch_id]):
        fname = str(path / f"{image_id}_L1A_{kind}.csv")
        try:
            df = pd.read_csv(fname)
        except FileNotFoundError:
            continue
        else:
            marking_ids = []
            for _ in range(df.shape[0]):
                marking_ids.append(next(id_))
            df["marking_id"] = marking_ids
            df.to_csv(fname, index=False)

# %% ../../notebooks/05_production.catalog.ipynb 9
def create_roi_file(obsids, roi_name, datapath):
    """Create a Region of Interest file, based on list of obsids.

    For more structured analysis processes, we can create a summary file for a list of obsids
    belonging to a ROI.
    The alternative is to define to what ROI any final object belongs to and add that as a column
    in the final catalog.

    Parameters
    ----------
    obsids : iterable of str
        List of HiRISE obsids
    roi_name : str
        Name for ROI
    datapath : str or pathlib.Path
        Path to the top folder with the clustering output data.
    """
    Bucket = dict(fan=[], blotch=[])
    for obsid in tqdm(obsids):
        pm = io.PathManager(obsid=obsid, datapath=datapath)
        # get all L1C folders for current obsid:
        folders = pm.get_obsid_paths("L1C")
        bucket = read_csvfiles_into_lists_of_frames(folders)
        for key, val in bucket.items():
            try:
                df = pd.concat(val, ignore_index=True, sort=False)
            except ValueError:
                continue
            else:
                df["obsid"] = obsid
                Bucket[key].append(df)
    savedir = pm.path_so_far.parent
    if len(Bucket) == 0:
        func = LOGGER.warning
    else:
        func = LOGGER.info
    func("Found %i fans and %i blotches.", len(Bucket["fan"]), len(Bucket["blotch"]))
    for key, val in Bucket.items():
        try:
            df = pd.concat(val, ignore_index=True, sort=False)
        except ValueError:
            continue
        else:
            savename = f"{roi_name}_{pm.L1C_folder}_{key}.csv"
            savepath = savedir / savename
            for col in ["x_tile", "y_tile"]:
                df[col] = pd.to_numeric(df[col], downcast="signed")
            if "version" in df.columns:
                df["version"] = pd.to_numeric(df["version"], downcast="signed")
            df.to_csv(savepath, index=False, float_format="%.2f")
            print(f"Created {savepath}.")


# %% ../../notebooks/05_production.catalog.ipynb 10
class ReleaseManager:
    """Class to manage releases and find relevant files.
    TODO better description
    Parameters
    ----------
    version : str
        Version string for this catalog. Same as datapath in other P4 code.
    obsids : iterable, optional
        Iterable of obsids that should be used for catalog file. Default is to use the full list of the default database, which is Seasons 2 and 3 at this point.
    overwrite : bool, optional
        Switch to control if already existing result folders for an obsid should be overwritten.
        Default: False
    """

    DROP_FOR_TILE_COORDS: list[str] = [
        "xy_hirise",
        "SampleResolution",
        "LineResolution",
        "PositiveWest360Longitude",
        "Line",
        "Sample",
    ]

    FAN_COLUMNS_AS_PUBLISHED: list[str] = [
        "marking_id",
        "angle",
        "distance",
        "tile_id",
        "image_x",
        "image_y",
        "n_votes",
        "obsid",
        "spread",
        "version",
        "vote_ratio",
        "x",
        "y",
        "x_angle",
        "y_angle",
        "l_s",
        "map_scale",
        "north_azimuth",
        "BodyFixedCoordinateX",
        "BodyFixedCoordinateY",
        "BodyFixedCoordinateZ",
        "PlanetocentricLatitude",
        "PlanetographicLatitude",
        "Longitude",
    ]
    BLOTCH_COLUMNS_AS_PUBLISHED: list[str] = [
        "marking_id",
        "angle",
        "tile_id",
        "image_x",
        "image_y",
        "n_votes",
        "obsid",
        "radius_1",
        "radius_2",
        "vote_ratio",
        "x",
        "y",
        "x_angle",
        "y_angle",
        "l_s",
        "map_scale",
        "north_azimuth",
        "BodyFixedCoordinateX",
        "BodyFixedCoordinateY",
        "BodyFixedCoordinateZ",
        "PlanetocentricLatitude",
        "PlanetographicLatitude",
        "Longitude",
    ]

    def __init__(self, version, obsids=None, overwrite=False, dbname=None):
        self.catalog = f"P4_catalog_{version}"
        self.overwrite = overwrite
        self._obsids: Iterable | None = obsids
        self.dbname = dbname

    @property
    def savefolder(self):
        "Path to catalog folder"
        return io.data_root / self.catalog

    @property
    def metadata_path(self):
        "Path to catalog metadata file."
        return self.savefolder / f"{self.catalog}_metadata.csv"

    @property
    def tile_coords_path(self):
        "Path to catalog tile coordinates file."
        return self.savefolder / f"{self.catalog}_tile_coords.csv"

    @property
    def tile_coords_path_final(self):
        "Path to final catalog tile coordinates file."
        return self.savefolder / f"{self.catalog}_tile_coords_final.csv"

    @property
    def obsids(self):
        """Return list of obsids for catalog production.

        If ._obsids is None, get default full obsids list for current default P4 database.
        """
        if self._obsids is None:
            db = io.DBManager(dbname=self.dbname)
            self._obsids = db.obsids
        return self._obsids

    @obsids.setter
    def obsids(self, values):
        """
        Sets the observation IDs.
        Parameters:
        values (list or array-like): A list or array of observation IDs to be set.
        """
        self._obsids = values

    @property
    def fan_file(self):
        "Return path to fan catalog file."
        try:
            return next(self.savefolder.glob("*_fan.csv"))
        except StopIteration:
            print(f"No file found. Looking at {self.savefolder}.")

    @property
    def blotch_file(self):
        "Return path to blotch catalog file."
        try:
            return next(self.savefolder.glob("*_blotch.csv"))
        except StopIteration:
            print(f"No file found. Looking at {self.savefolder}.")

    @property
    def fan_merged(self):
        """
        Generates the file path for the merged fan metadata CSV file.
        Returns:
            pathlib.Path: The path to the merged fan metadata CSV file, 
                          constructed by appending '_meta_merged.csv' to the stem of the original fan file.
        """
        
        return self.fan_file.parent / f"{self.fan_file.stem}_meta_merged.csv"

    @property
    def blotch_merged(self):
        return self.blotch_file.parent / f"{self.blotch_file.stem}_meta_merged.csv"

    def read_fan_file(self):
        return pd.read_csv(self.fan_merged)

    def read_blotch_file(self):
        return pd.read_csv(self.blotch_merged)

    def mark_done(self,obsid):
        """Create a simple file in each obsid folder, that is simply meant to show that this obsid was finished for the todo method.

        Parameters
        ----------
        obsid : str
            Corresponding obsid
        """
        pm = io.PathManager(obsid=obsid, datapath=self.savefolder)
        path = pm.obsid_results_savefolder / obsid / "Done.txt"
        with open(path, "w") as file:
            file.write("Done")
    

    def check_for_todo(self, overwrite=None):
        if overwrite is None:
            overwrite = self.overwrite
        bucket = []
        for obsid in self.obsids:
            pm = io.PathManager(obsid=obsid, datapath=self.savefolder)
            path = pm.obsid_results_savefolder / obsid / "Done.txt"
            if path.exists() and overwrite is False:
                continue
            else:
                bucket.append(obsid)
        self.todo = bucket

    def get_parallel_args(self):
        return [(i, self.catalog, self.dbname) for i in self.todo]

    def get_no_of_tiles_per_obsid(self):
        all_data = pd.read_parquet(self.dbname)
        return all_data.groupby("image_name").image_id.nunique()

    @property
    def EDRINDEX_meta_path(self):
        return self.savefolder / f"{self.catalog}_EDRINDEX_metadata.csv"

    def calc_metadata(self):
        if not self.EDRINDEX_meta_path.exists():
            NAs = p4meta.get_north_azimuths_from_SPICE(self.obsids)
            edrindex = get_index("mro.hirise", "edr")
            p4_edr = (
                edrindex[edrindex.OBSERVATION_ID.isin(self.obsids)]
                .query('CCD_NAME=="RED4"')
                .drop_duplicates(subset="OBSERVATION_ID")
            )
            p4_edr = p4_edr.set_index("OBSERVATION_ID").join(
                NAs.set_index("OBSERVATION_ID")
            )
            p4_edr = p4_edr.join(self.get_no_of_tiles_per_obsid())
            p4_edr.rename(dict(image_id="# of tiles"), axis=1, inplace=True)
            p4_edr["map_scale"] = 0.25 * p4_edr.BINNING
            p4_edr.reset_index(inplace=True)
            p4_edr.to_csv(self.EDRINDEX_meta_path)
        else:
            p4_edr = pd.read_csv(self.EDRINDEX_meta_path)
        cols = [
            "OBSERVATION_ID",
            "IMAGE_CENTER_LATITUDE",
            "IMAGE_CENTER_LONGITUDE",
            "SOLAR_LONGITUDE",
            "START_TIME",
            "map_scale",
            "north_azimuth",
            "# of tiles",
        ]
        metadata = p4_edr[cols]
        metadata.to_csv(self.metadata_path, index=False, float_format="%.7f")
        LOGGER.info("Wrote %s", str(self.metadata_path))

    def calc_tile_coordinates(self):
        cubepaths = [P4Mosaic(obsid).mosaic_path for obsid in self.obsids]

        todo = []
        for cubepath in tqdm(cubepaths,desc="Appending Cubepaths"):
            tc = TileCalculator(cubepath, read_data=False, dbname=self.dbname)
            if not tc.campt_results_path.exists():
                todo.append(cubepath)

        def get_tile_coords(cubepath):
            from p4tools.production.projection import TileCalculator##TODO is that import necessary

            tilecalc = TileCalculator(cubepath, dbname=self.dbname)
            tilecalc.calc_tile_coords()

        if not len(todo) == 0:
            for cubepath in tqdm(todo,desc="Calculating Tile Coords"):
                _ = get_tile_coords(cubepath)

        bucket = []
        for cubepath in tqdm(cubepaths,desc="Creating Cubepath Bucket"):
            tc = TileCalculator(cubepath, read_data=False, dbname=self.dbname)
            bucket.append(tc.tile_coords_df)
        coords = pd.concat(bucket, ignore_index=True, sort=False)
        coords.to_csv(self.tile_coords_path, index=False, float_format="%.7f")
        LOGGER.info("Wrote %s", str(self.tile_coords_path))

    @property
    def COLS_TO_MERGE(self):
        return [
            "obsid",
            "image_x",
            "image_y",
            "BodyFixedCoordinateX",
            "BodyFixedCoordinateY",
            "BodyFixedCoordinateZ",
            "PlanetocentricLatitude",
            "PlanetographicLatitude",
            "PositiveEast360Longitude",
        ]

    def merge_fnotch_results(self, fans, blotches):
        """Average multiple objects from fnotching into one.

        Because fnotching can compare the same object with more than one, it can appear more than once
        with different `vote_ratio` values in the results. We merge them here into one, simply
        averaging the vote_ratio. This increases the value of the `vote_ratio` number as it now
        has been created by several comparisons. It only occurs for 0.5 % of fans though.
        """
        out = []
        for df in [fans, blotches]:
            #This grouping by obsid and marking_id is necessary for the case that we do parallel processing which will create duplicate marking ids per obsid
            averaged = df.groupby(["obsid","marking_id"]).mean(numeric_only=True) 
            tmp = df.drop_duplicates(subset=["marking_id","obsid"]).set_index(["obsid","marking_id"])
            averaged = averaged.join(tmp[["image_id"]],how="inner")
            out.append(averaged.reset_index())

        return out

    def merge_all(self):
        # read in data files
        fans = pd.read_csv(self.fan_file)
        blotches = pd.read_csv(self.blotch_file)
        meta = pd.read_csv(self.metadata_path, dtype="str")
        tile_coords = pd.read_csv(self.tile_coords_path, dtype="str")

        # average multiple fnotch results
        fans, blotches = self.merge_fnotch_results(fans, blotches)

        # merge meta
        cols_to_merge = [
            "OBSERVATION_ID",
            "SOLAR_LONGITUDE",
            "north_azimuth",
            "map_scale",
        ]
        fans = fans.merge(
            meta[cols_to_merge], left_on="obsid", right_on="OBSERVATION_ID"
        )
        blotches = blotches.merge(
            meta[cols_to_merge], left_on="obsid", right_on="OBSERVATION_ID"
        )

        # drop unnecessary columns
        tile_coords.drop(
            self.DROP_FOR_TILE_COORDS, axis=1, inplace=True, errors="ignore"
        )
        # save cleaned tile_coords
        tile_coords.rename({"image_id": "tile_id"}, axis=1, inplace=True)
        tile_coords.to_csv(
            self.tile_coords_path_final, index=False, float_format="%.7f"
        )

        # merge campt results into catalog files
        fans, blotches = self.merge_campt_results(fans, blotches)

        # write out fans catalog
        fans["vote_ratio"] = fans["vote_ratio"].fillna(1)
        fans.version = fans.version.astype("int")
        fans.rename(
            {
                "image_id": "tile_id",
                "SOLAR_LONGITUDE": "l_s",
                "PositiveEast360Longitude": "Longitude",
            },
            axis=1,
            inplace=True,
        )
        fans[self.FAN_COLUMNS_AS_PUBLISHED].to_csv(self.fan_merged, index=False, mode = "w")

        LOGGER.info("Wrote %s", str(self.fan_merged))

        # write out blotches catalog
        blotches["vote_ratio"] = blotches["vote_ratio"].fillna(1)
        blotches.rename(
            {
                "image_id": "tile_id",
                "SOLAR_LONGITUDE": "l_s",
                "PositiveEast360Longitude": "Longitude",
            },
            axis=1,
            inplace=True,
        )
        blotches[self.BLOTCH_COLUMNS_AS_PUBLISHED].to_csv(
            self.blotch_merged, index=False, mode = "w"
        )
        LOGGER.info("Wrote %s", str(self.blotch_merged))

    def calc_marking_coordinates(self):
        fans = pd.read_csv(self.fan_file)
        blotches = pd.read_csv(self.blotch_file)
        combined = pd.concat([fans, blotches], sort=False)

        obsids_with_data = combined.image_name.unique()
        
        if len(self.obsids) != len(obsids_with_data):
            
            missing = list(set(self.obsids) - set(obsids_with_data))

            LOGGER.warn("The following obsids have no data from clustering")
            LOGGER.warn(missing)

        for obsid in tqdm(obsids_with_data):
            data = combined[combined.image_name == obsid]
            xy = XY2LATLON(data, self.savefolder, overwrite=self.overwrite)
            xy.process_inpath()


    def collect_marking_coordinates(self,obsids = None):
        bucket = []

        if type(obsids) is np.ndarray:
            working_obsids = obsids
        else:
            working_obsids = self.obsids
            
        for obsid in working_obsids:
            xy = XY2LATLON(None, self.savefolder, obsid=obsid)
            bucket.append(pd.read_csv(xy.savepath).assign(obsid=obsid))

        ground = pd.concat(bucket, sort=False).drop_duplicates()
        ground.rename(dict(Sample="image_x", Line="image_y"), axis=1, inplace=True)
        return ground

    def fix_marking_coordinates_precision(self, df):
        fname = "tempfile.csv"
        df.to_csv(fname, float_format="%.7f")
        return pd.read_csv(fname, dtype="str")

    def merge_campt_results(self, fans, blotches):
        INDEX = ["obsid", "image_x", "image_y"]

        ## This part is necessary for the case in which not all obsids have data left after clustering
        obsids_1 = fans.obsid.unique()
        obsids_2 = blotches.obsid.unique()
        obsids = np.append(obsids_1,obsids_2)
        obsids = np.unique(obsids)

        ground = self.collect_marking_coordinates(obsids).round(decimals=7)
        # ground = self.fix_marking_coordinates_precision(ground)
        fans = fans.merge(ground[self.COLS_TO_MERGE], on=INDEX)
        blotches = blotches.merge(ground[self.COLS_TO_MERGE], on=INDEX)
        return fans, blotches
    
    def fix_marking_ids(self):
        """
        This function is supposed to be called to fix the marking IDs when parallely proccessed
        """

        bucket = [(self.fan_merged,fan_id_generator),(self.blotch_merged,blotch_id_generator)]
        
        for path, gen in bucket:
            df = pd.read_csv(path)
            length = df.shape[0]

            markingid = np.zeros(df.shape[0],dtype=str)
            generator_marking = gen()

            markingid = []
            for i in range(length):

                markingid.append(next(generator_marking))

            df["marking_id"] = markingid
            assert df.marking_id.unique().size == length
            df.to_csv(path, index=False)


    def launch_catalog_production(self,kind : str = "serial", parallel_tasks : int = 10):

        if kind == "serial":
            self.launch_serial_production()
        
        if kind == "parallel":
            self.launch_parallel_production(parallel_tasks=parallel_tasks)


    def launch_parallel_production(self,parallel_tasks : int = 10):
        """
        Launches the production process in parallel.
        This method performs several tasks in parallel, including clustering, 
        fnotching, and creating mosaics. It also generates summary CSV files, 
        calculates ground coordinates, and writes metadata.

        USE AT YOUR OWN RISK. Does not scale very well. 
        It is recommended to do process paraellism with:
        ReleaseManager.produce_single_obsid(...)

        Args:
            parallel_tasks (int, optional): The number of parallel tasks to run. 
                                            Defaults to 10.
        Raises:
            Exception: If there is an issue with slicing the obsids list.
        """

        self.check_for_todo()
        
        fan_id = fan_id_generator()
        blotch_id = blotch_id_generator()

        #Simple trick to start too many tasks at the same time which all load a large DB.
        total = len(self.todo)
        #adding 1 to the loop amount is important to finish up the leftovers that dont fit in total/n_workers
        # Example total = 10; n_workers = 3 => 10/3 = 3 meaning 3 loops until 0:3, 3:6, 6:9 , missing the last one 10
        if total%parallel_tasks == 0:
            loop_full = int(total/parallel_tasks)
        else:
            loop_full = int(np.floor(total/parallel_tasks)) + 1 
        
        for i in range(loop_full):
            try: 
                temp_obsids = self.obsids[parallel_tasks*i:parallel_tasks*i+parallel_tasks]
            except:
                temp_obsids = self.obsids[parallel_tasks*i:]

            LOGGER.info(f"Performing the Clustering for batch {i}")
            _ = cluster_obsid_parallel(temp_obsids, self.catalog, self.dbname)

            for obsid in temp_obsids:
                paths = get_L1A_paths(obsid, self.catalog)
                for path in paths:
                    add_marking_ids(path, fan_id, blotch_id)
            
            # fnotch and apply cuts
            LOGGER.info("Start fnotching")
            _ = fnotch_obsid_parallel(temp_obsids, self.catalog)

            LOGGER.info("Creating the required RED45 mosaics for ground projections.")
            _ = execute_in_parallel(create_RED45_mosaic, temp_obsids)


        # create summary CSV files of the clustering output
        LOGGER.info("Creating L1C fan and blotch database files.")
        create_roi_file(self.obsids, self.catalog, self.catalog)

        LOGGER.info("Calculating the center ground coordinates for all P4 tiles.")
        self.calc_tile_coordinates()

        LOGGER.info("Calculating ground coordinates for catalog.")
        self.calc_marking_coordinates()

        # calculate all metadata required for P4 analysis
        LOGGER.info("Writing summary metadata file.")
        self.calc_metadata()
        # merging metadata
        self.merge_all()

    
    def launch_serial_production(self):
        """The Method for starting the production of the catalogue in a serial manner. Doing one OBSID at a time.
        """
        self.check_for_todo()

        fan_id = fan_id_generator()
        blotch_id = blotch_id_generator()

        for obsid in self.todo:

            LOGGER.info(f"Performing the Clustering for {obsid}")
            if len(self.todo) > 0:
                cluster_obsid(obsid,self.catalog,dbname=self.dbname)

                paths = get_L1A_paths(obsid, self.catalog)
                for path in paths:
                    add_marking_ids(path, fan_id, blotch_id)

                LOGGER.info(f"Start fnotching for {obsid}")
                fnotch_obsid(obsid,savedir=self.catalog)

                create_RED45_mosaic(obsid)

                self.mark_done(obsid)

        LOGGER.info("Creating L1C fan and blotch database files.")
        create_roi_file(self.obsids, self.catalog, self.catalog)

        LOGGER.info("Calculating the center ground coordinates for all P4 tiles.")
        self.calc_tile_coordinates()

        LOGGER.info("Calculating ground coordinates for catalog.")
        self.calc_marking_coordinates()

        # calculate all metadata required for P4 analysis
        LOGGER.info("Writing summary metadata file.")
        self.calc_metadata()
        # merging metadata
        self.merge_all()

    def produce_single_obsid(self, obsid:str,  makeMosaics = True):
        """Clusters and creates all obsid data without merging 
           as this should only be done on the full catalog. This
           is meant for repairing single obsids

        Parameters
        ----------
        obsid : str
            One Singular obsid
        makeMosaics : bool
            wether you want to redownload and create the RED45 mosaics (not always necessary when rerunning)
        """

        fan_id = fan_id_generator()
        blotch_id = blotch_id_generator()

        cluster_obsid(obsid,self.catalog,dbname=self.dbname)

        paths = get_L1A_paths(obsid, self.catalog)
        for path in paths:
            add_marking_ids(path, fan_id, blotch_id)

        LOGGER.info(f"Start fnotching for {obsid}")
        fnotch_obsid(obsid,savedir=self.catalog)

        if makeMosaics:
            create_RED45_mosaic(obsid)
        
        self.mark_done(obsid)



# %% ../../notebooks/05_production.catalog.ipynb 11
def read_csvfiles_into_lists_of_frames(folders):
    """
    Reads CSV files from given folders into lists of DataFrames.
    This function iterates over a list of folders, reads CSV files within those folders,
    and categorizes them into two lists: 'fan' and 'blotch'. The categorization is based
    on the filename ending with 'fans.csv' or blotch.csv.
    Args:
        folders (list of pathlib.Path): A list of folder paths to search for CSV files.
    Returns:
        dict: A dictionary with two keys, 'fan' and 'blotch', each containing a list of
              pandas DataFrames read from the CSV files.
    """
    
    bucket = dict(fan=[], blotch=[])
    for folder in folders:
        for markingfile in folder.glob("*.csv"):
            key = "fan" if markingfile.name.endswith("fans.csv") else "blotch"
            bucket[key].append(pd.read_csv(markingfile))
    return bucket
