# AUTOGENERATED! DO NOT EDIT! File to edit: ../../notebooks/05e_production.dbscan.ipynb.

# %% auto 0
__all__ = ['logger', 'plot_results', 'DBScanner']

# %% ../../notebooks/05e_production.dbscan.ipynb 2
from . import io,markings


from sklearn.cluster import DBSCAN
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.stats import circmean, circstds
import pyaml
from pathlib import Path
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# %% ../../notebooks/05e_production.dbscan.ipynb 3
def plot_results(p4id, labels, data=None, kind=None, reduced_data=None, ax=None):
    functions = dict(blotch=p4id.plot_blotches, fan=p4id.plot_fans)
    if ax is None:
        _, ax = plt.subplots()

    plot_kwds = {"alpha": 0.8, "s": 10, "linewidths": 0}
    palette = sns.color_palette("bright", len(labels))
    cluster_colors = [palette[x] if x >= 0 else (0.75, 0.75, 0.75) for x in labels]
    p4id.show_subframe(ax=ax)
    if data is not None:
        ax.scatter(data.loc[:, "x"], data.loc[:, "y"], c=cluster_colors, **plot_kwds)
    markings.set_subframe_size(ax)
    # pick correct function for kind of marking:
    if any(reduced_data):
        functions[kind](ax=ax, data=reduced_data, lw=1, with_center=True)



# %% ../../notebooks/05e_production.dbscan.ipynb 4
class DBScanner:
    """

    Parameters
    ----------
    msf : float
        m_ean s_amples f_actor: Factor to multiply number of markings with to calculate the
        min_samples value for DBSCAN to use
    savedir : str, pathlib.Path
        Path where to store clustered results
    with_angles, with_radii : bool
        Switches to control if clustering should include angles and radii respectively.
    do_large_run : bool
        Switch to control if a second run with parameters set for large objects should
        be done.
    save_results : bool
        Switch to control if the resulting clustered objects should be written to disk.
    """

    def __init__(
        self,
        msf=0.13,
        savedir=None,
        with_angles=True,
        with_radii=True,
        do_large_run=True,
        save_results=True,
        only_core_samples=False,
        data=None,
        dbname=None,
    ):
        self.msf = msf
        self.savedir = savedir
        self.with_angles = with_angles
        self.with_radii = with_radii
        self.do_large_run = do_large_run
        self.save_results = save_results
        self.only_core_samples = only_core_samples
        self.data = data
        self.pm = io.PathManager(datapath=savedir)
        self.noise = []
        self.dbname = dbname

        # This needs to be on instance level, so that a new object always has these default numbers
        # It sets all the different eps values for the different clustering loops here:
        self.eps_values = {
            "fan": {
                "xy": {"small": 10, "large": 25},  # in pixels
                "angle": 20,  # degrees
                "radius": {
                    "small": None,  # not in use currently for fans`
                    "large": None,  # ditto
                },
            },
            "blotch": {
                "xy": {"small": 10, "large": 25},  # in pixels
                "angle": None,  # for now deactivated
                "radius": {"small": 30, "large": 50},
            },
        }

    def show_markings(self, id_):
        p4id = markings.TileID(id_)
        p4id.plot_all()

    def cluster_any(self, X, eps):
        logger.debug("Clustering any.")
        db = DBSCAN(eps, min_samples=self.min_samples).fit(X)
        labels = db.labels_
        unique_labels = sorted(set(labels))

        core_samples_mask = np.zeros_like(labels, dtype=bool)
        core_samples_mask[db.core_sample_indices_] = True

        self.n_clusters = len(unique_labels) - (1 if -1 in labels else 0)
        logger.debug("%i cluster(s) found with:", self.n_clusters)

        self.labels = labels

        # loop over unique labels.
        for k in unique_labels:
            class_member_mask = (labels == k)
            if k == -1:
                self.noise.append(class_member_mask)
                continue
            if self.only_core_samples is True:
                # this has a potentially large effect and can make the number
                # of surviving cluster_members smaller than 3 !
                indices = class_member_mask & core_samples_mask
            else:
                indices = class_member_mask
            logger.debug("%i members.", np.count_nonzero(indices))
            yield indices

    def cluster_xy(self, data, eps):
        logger.info("Clustering x,y with eps: %i", eps)
        X = data[["x", "y"]].values
        for cluster_index in self.cluster_any(X, eps):
            yield data.loc[cluster_index]

    def split_markings_by_size(self, data, limit=210):
        kind = data.marking.value_counts()
        if len(kind) > 1:
            raise TypeError("Data had more than 1 marking kind.")
        if kind.index[0] == "blotch":
            f1 = data.radius_1 > limit
            f2 = data.radius_2 > limit
            data_large = data[f1 | f2]
            data_small = data
        else:
            f1 = data.distance > limit
            data_large = data[f1]
            data_small = data[~f1]
        return data_small, data_large

    def cluster_angles(self, xy_clusters, kind):
        cols_to_cluster = dict(blotch=["y_angle"], fan=["x_angle", "y_angle"])
        eps_degrees = self.eps_values[kind]["angle"]
        logger.info("Clustering angles with eps: %i", eps_degrees)
        # convert to radians
        # calculated value of euclidean distance of unit vector
        # end points per degree
        eps_per_degree = np.pi*2 / 360
        eps = eps_degrees * eps_per_degree
        for xy_cluster in xy_clusters:
            X = xy_cluster[cols_to_cluster[kind]]
            for indices in self.cluster_any(X, eps):
                yield xy_cluster.loc[indices]

    def cluster_radii(self, angle_clusters, eps):
        logger.info("Clustering radii with eps: %i", eps)
        cols_to_cluster = ["radius_1", "radius_2"]
        for angle_cluster in angle_clusters:
            X = angle_cluster[cols_to_cluster]
            for indices in self.cluster_any(X, eps):
                yield angle_cluster.loc[indices]

    def cluster_and_plot(
        self,
        img_id,
        kind,
        msf=None,
        eps_values=None,
        ax=None,
        fontsize=None,
        saveplot=True,
    ):
        """Cluster and plot the results for one P4 image_id.

        Parameters
        ----------
        img_ig : str
            Planet Four image_id
        kind : {'fan', 'blotch'}
            Kind of marking
        eps_values : dictionary, optional
            Dictionary with clustering values to be used. If not given, use stored default one.
            This is mostly used for `self.parameter_scan`.
        ax : matplotlib.axis, optional
            Matplotlib axis to be used for plotting. If not given, a new figure and axis is
            created.
        fontsize : int, optional
            Fontsize for the plots' headers.
        """
        if msf is not None:
            self.msf = msf
        if eps_values is None:
            # if not given, use stored default values:
            eps_values = self.eps_values

        self.cluster_image_id(img_id, msf, eps_values)

        reduced_data = self.reduced_data[kind]

        try:
            n_reduced = len(reduced_data)
        except TypeError:
            n_reduced = 0

        if ax is None:
            fig, ax = plt.subplots()
        else:
            fig = ax.get_figure()
        if n_reduced > 0:
            plot_results(
                self.p4id, self.labels, kind=kind, reduced_data=reduced_data, ax=ax
            )
        else:
            self.p4id.show_subframe(ax=ax)
        eps = eps_values[kind]["xy"]["small"]
        eps_large = eps_values[kind]["xy"]["large"]
        ax.set_title(
            f"ID: {img_id}, "
            f"n: {n_reduced}\n"
            f"MS: {self.min_samples}, "
            f"EPS: {eps}, "
            f"EPS_LARGE: {eps_large}",
            fontsize=fontsize,
        )
        if saveplot:
            savepath = f"plots/{img_id}_{kind}_eps{eps}_epsLARGE{eps_large}.png"
            Path(savepath).parent.mkdir(exist_ok=True)
            fig.savefig(savepath, dpi=200)

    @property
    def min_samples(self):
        """Calculate min_samples for DBSCAN.

        From current self.msf value and no of classifications.
        """
        min_samples = round(self.msf * self.p4id.n_marked_classifications)
        return max(3, min_samples)  # never use less than 3

    def setup_logfiles(self):
        if len(logger.handlers) > 0:
            for handler in logger.handlers:
                if isinstance(handler, logging.FileHandler):
                    logger.debug("Found logging.FileHandler")
                    return
        logpath = self.pm.path_so_far / "clustering.log"
        logpath.parent.mkdir(exist_ok=True, parents=True)
        fh = logging.FileHandler(logpath, "w")
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s" " - %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        # logger.setLevel(logging.INFO)

    def cluster_image_name(self, image_name, msf=None, eps_values=None):
        "Cluster all image_ids for a given image_name (i.e. HiRISE obsid)"
        if msf is not None:
            self.msf = msf
        self.pm.obsid = image_name
        self.setup_logfiles()

        logger.info("Clustering image_name %s with msf of %f.", image_name, self.msf)
        db = io.DBManager(self.dbname)
        data = db.get_image_name_markings(image_name)
        image_ids = data.image_id.unique()
        logger.debug("Number of image_ids found: %i", len(image_ids))
        for image_id in tqdm(image_ids):
            self.pm.id = image_id
            self.cluster_image_id(image_id, msf, eps_values, image_name)

    def write_settings_file(self, eps_values):
        eps_values["min_samples"] = self.min_samples
        eps_values["only_core_samples"] = self.only_core_samples
        settingspath = self.pm.blotchfile.parent / "clustering_settings.yaml"
        settingspath.parent.mkdir(exist_ok=True, parents=True)
        logger.info("Writing settings file at %s", str(settingspath))
        with open(settingspath, "w") as fp:
            pyaml.dump(eps_values, fp)

    def cluster_image_id(self, img_id, msf=None, eps_values=None, image_name=None):
        """Interface function for users to cluster data for one P4 image_id.

        This method does the data splitting in case it is required and calls the
        `_setup_and_call_clustering` that goes over all dimensions to cluster.


        Parameters
        ----------
        img_ig : str
            Planet Four image_id
        msf : float, optional
            mean_samples_factor to be used for calculating min_samples. Default as given
            during __init__.
        eps_values : dictionary, optional
            Dict with eps values for clustering, in the format as given in `self.eps_values`.
            If not provided, the default stored `self.eps_values` is used.

        Returns
        -------
        At the end the data from differently-sized clustering is concatenated into the same
        results pd.DataFrame and then being stored per marking kind in the dictionary
        `self.reduced_data`.
        """
        self.p4id = markings.TileID(
            img_id, scope="p4tools", dbname=self.dbname, data=self.data, image_name=image_name
        )
        self.pm.obsid = self.p4id.image_name
        self.pm.id = img_id

        # this will setup the logfile if we have not been called via image_name
        # clustering already.
        self.setup_logfiles()

        logger.info("Clustering id: %s with min_samples: %i", img_id, self.min_samples)
        if msf is not None:
            # this sets the stored msf, automatically changing min_samples accordingly
            self.msf = msf

        eps_values = self.eps_values if eps_values is None else eps_values
        self.write_settings_file(eps_values)
        # set up storage for results
        self.reduced_data = {}
        self.final_clusters = {}
        old_val = self.do_large_run
        for kind in ["fan", "blotch"]:
            logger.info("Working on %s.", kind)
            self.current_kind = kind
            if kind == "fan":
                self.do_large_run = False
            else:
                self.do_large_run = old_val
            # fill in empty lists in case we need to bail for not enough data
            self.final_clusters[kind] = []
            self.reduced_data[kind] = []
            # Receive the fans or blotches, respectively:
            data = self.p4id.filter_data(kind)
            if len(data) < self.min_samples:
                # skip all else if we have not enough markings
                continue
            # cluster first with the parameters for small objects
            self._setup_and_call_clustering(eps_values, data, kind, "small")
            # self.remaining was created during previous call.
            if len(self.remaining) > self.min_samples and self.do_large_run is True:
                # if we allow it, and more than min_samples are left, do 2nd round
                # with parameters for large objects
                logger.info("Clustering on remaining data with large parameter set.")
                self._setup_and_call_clustering(
                    eps_values, self.remaining, kind, "large"
                )
            # merging small and large clustering results
            try:
                self.reduced_data[kind] = pd.concat(
                    self.reduced_data[kind], ignore_index=True, sort=True
                )
            except ValueError:
                # i can just continue here, as I stored an empty list above already
                continue

        if self.save_results:
            self.store_clustered(self.reduced_data)

    def _setup_and_call_clustering(self, eps_values, dataset, kind, size):
        """setup helper for the clustering pipeline.

        This just reads out the values from the eps_values structure and then calls
        `_cluster_pipeline`.
        """
        logger.info("Processing %s dataset.", size)
        eps_xy = eps_values[kind]["xy"][size]
        eps_rad = eps_values[kind]["radius"][size]
        logger.debug("Length of dataset: %i", len(dataset))
        self.reduced_data[kind].append(
            self._cluster_pipeline(kind, dataset, eps_xy, eps_rad)
        )
        logger.debug("Appending %i items to final_clusters", len(self.finalclusters))
        self.final_clusters[kind].append(self.finalclusters)

    def _calculate_unclustered(self, data, xyclusters):
        data_in = data.dropna(how="all", axis=1)
        try:
            clustered = pd.concat(xyclusters).dropna(how="all", axis=1)
        except ValueError:
            self.remaining = []
        else:
            self.remaining = data_in[~data_in.isin(clustered).all(1)]
        if self.current_kind == "blotch" and len(self.remaining) > 0:
            eps = 0.00001
            blotch_defaults = ((self.remaining.radius_1 - 10) < eps) & (
                (self.remaining.radius_2 - 10).abs() < eps
            )
            self.remaining = self.remaining[~blotch_defaults]

    def _cluster_pipeline(self, kind, data, eps, eps_rad):
        """Cluster pipeline that can cluster over xy, angles and radii.

        It does so without knowledge of different marking sizes, it just receives data and
        will cluster it together, successively.
        """
        xyclusters = self.cluster_xy(data, eps)
        xyclusters = list(xyclusters)
        self._calculate_unclustered(data, xyclusters)
        if self.with_radii and eps_rad is not None:
            last = self.cluster_radii(xyclusters, eps_rad)
        else:
            last = xyclusters
        last = list(last)
        if self.with_angles and self.eps_values[kind]["angle"] is not None:
            finalclusters = self.cluster_angles(last, kind)
        else:
            finalclusters = last
        last = list(last)
        finalclusters = list(finalclusters)
        self.finalclusters = finalclusters
        averaged = get_average_objects(finalclusters, kind)
        try:
            reduced_data = pd.concat(averaged, ignore_index=True, sort=True)
        except ValueError as e:
            if e.args[0].startswith("No objects to concatenate"):
                # logger.warning("No clusters survived.")
                return None
            else:
                raise e
        return reduced_data

    def parameter_scan(
        self,
        img_id,
        kind,
        msf_vals_to_scan,
        eps_vals_to_scan,
        size_to_scan="large",
        do_scale=False,
        create_plot=True,
    ):
        """Method to scan parameter space and plot results in multi-figure plot.

        Parameters
        ----------
        kind : {'fan', 'blotch'}
            Marking kind
        msf_values : iterable (list, array, tuple), length of 2
            1D container for msf values to use
        eps_values : iterable, length of 3
            1D container for eps_values to be used. If they are used for the small or large
            items is determined by `size_to_scan`
        size_to_scan : {'small', 'large'}
            Switch to interpret which eps_values I have received. If 'small' to scan, I take
            the large value from `self.eps_values` as constant, and vice versa.
        do_scale : bool
            Switch to control if scaling is applied.
        """
        self.kind = kind
        fig, ax = plt.subplots(
            nrows=len(msf_vals_to_scan),
            ncols=len(eps_vals_to_scan) + 1,
            figsize=(10, 5),
        )
        axes = ax.flatten()

        for ax, (msf, eps) in zip(axes, product(msf_vals_to_scan, eps_vals_to_scan)):
            eps_values = self.eps_values.copy()

            eps_values[kind]["xy"][size_to_scan] = eps

            self.cluster_and_plot(
                img_id, kind, msf, eps_values, ax=ax, fontsize=8, saveplot=False
            )
            t = ax.get_title()
            ax.set_title("MSF: {}, {}".format(msf, t), fontsize=8)

        # plot input tile
        self.p4id.show_subframe(ax=axes[-1])
        axes[-1].set_title("Input tile", fontsize=8)
        # plot marking data
        self.p4id.plot_markings(kind, ax=axes[-2], lw=0.25, with_center=True)
        axes[-2].set_title("{} marking data".format(kind), fontsize=8)
        fig.suptitle(
            "ID: {}, n_class: {}, angles: {}, radii: {}".format(
                img_id,
                self.p4id.n_marked_classifications,
                self.with_angles,
                self.with_radii,
            )
        )
        if create_plot:
            savepath = f"plots/{img_id}_{kind}_angles{self.with_angles}_radii{self.with_radii}.png"
            Path(savepath).parent.mkdir(exist_ok=True)
            fig.savefig(savepath, dpi=200)

    @property
    def n_clustered_fans(self):
        """int : Number of clustered fans."""
        return len(self.reduced_data["fan"])

    @property
    def n_clustered_blotches(self):
        """int : Number of clustered blotches."""
        return len(self.reduced_data["blotch"])

    def store_clustered(self, reduced_data):
        "Store the clustered but as of yet unfnotched data."

        logger.debug("Storing reduced_data.")
        # get the PathManager object
        pm = self.pm

        for outpath, outdata in zip(
            [pm.blotchfile, pm.fanfile], [reduced_data["blotch"], reduced_data["fan"]]
        ):
            outpath.parent.mkdir(exist_ok=True, parents=True)
            if outpath.exists():
                outpath.unlink()
            if not any(outdata):
                logger.debug("No data for %s", str(outpath))
                continue
            df = outdata
            try:
                df["n_votes"] = df["n_votes"].astype("int")
                df["image_id"] = self.pm.id
                df["image_name"] = self.pm.obsid
            # when df is just list of Nones, will create TypeError
            # for bad indexing into list.
            except TypeError:
                # nothing to write
                logger.warning("Outdata was empty, nothing to store.")
                return
            df.to_csv(str(outpath.with_suffix(".csv")), index=False)
            logger.debug("Wrote %s", str(outpath.with_suffix(".csv")))
