#!/usr/bin/env python
# coding: utf-8
# example usage: python compute_nhd_routing_SingleSeg.py -v -t -w -n Mainstems_CONUS


# -*- coding: utf-8 -*-
"""NHD Network traversal

A demonstration version of this code is stored in this Colaboratory notebook:
    https://colab.research.google.com/drive/1ocgg1JiOGBUl3jfSUPCEVnW5WNaqLKCD

"""
## Parallel execution
import os
import sys
import time
import numpy as np
import argparse
import pathlib
import pandas as pd
from collections import defaultdict
from functools import partial
from joblib import delayed, Parallel
from itertools import chain, islice
from operator import itemgetter


def _handle_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--debuglevel",
        help="Set the debuglevel",
        dest="debuglevel",
        choices=[0, 1, 2, 3],
        default=0,
        type=int,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Verbose output (leave blank for quiet output)",
        dest="verbose",
        action="store_true",
    )
    parser.add_argument(
        "--nts",
        "--number-of-qlateral-timesteps",
        help="Set the number of timesteps to execute. If used with ql_file or ql_folder, nts must be less than len(ql) x qN.",
        dest="nts",
        default=144,
        type=int,
    )
    parser.add_argument(
        "--sts",
        "--assume-short-ts",
        help="Use the previous timestep value for upstream flow",
        dest="assume_short_ts",
        action="store_true",
    )
    parser.add_argument(
        "-ocsv",
        "--write-output-csv",
        nargs="?",
        help="Write csv output files to this folder (omit flag for no csv writing)",
        dest="csv_output_folder",
        const="../../test/output/text",
    )
    parser.add_argument(
        "-t",
        "--showtiming",
        help="Set the showtiming (leave blank for no timing information)",
        dest="showtiming",
        action="store_true",
    )
    parser.add_argument(
        "-w",
        "--break-at-waterbodies",
        help="Use the waterbodies in the route-link dataset to divide the computation (leave blank for no splitting)",
        dest="break_network_at_waterbodies",
        action="store_true",
    )
    parser.add_argument(
        "--parallel",
        nargs="?",
        help="Use the parallel computation engine (omit flag for serial computation)",
        dest="parallel_compute_method",
        const="by-network",
    )
    parser.add_argument(
        "--subnet-size",
        help="Set the target size (number of segments) for grouped subnetworks.",
        dest="subnetwork_target_size",
        default=-1,
        type=int,
    )
    parser.add_argument(
        "--cpu-pool",
        help="Assign the number of cores to multiprocess across.",
        dest="cpu_pool",
        type=int,
        default=-1,
    )
    parser.add_argument(
        "--compute_method",
        help="Use the cython version of the compute_network code (enter additional flag options for other compute_network possibilities).",
        dest="compute_method",
        default="standard cython compute network",
    )
    parser.add_argument(
        "-n",
        "--supernetwork",
        help="Choose from among the pre-programmed supernetworks (Pocono_TEST1, Pocono_TEST2, LowerColorado_Conchos_FULL_RES, Brazos_LowerColorado_ge5, Brazos_LowerColorado_FULL_RES, Brazos_LowerColorado_Named_Streams, CONUS_ge5, Mainstems_CONUS, CONUS_Named_Streams, CONUS_FULL_RES_v20",
        choices=[
            "Pocono_TEST1",
            "Pocono_TEST2",
            "LowerColorado_Conchos_FULL_RES",
            "Brazos_LowerColorado_ge5",
            "Brazos_LowerColorado_FULL_RES",
            "Brazos_LowerColorado_Named_Streams",
            "CONUS_ge5",
            "Mainstems_CONUS",
            "CONUS_Named_Streams",
            "CONUS_FULL_RES_v20",
        ],
        # TODO: accept multiple or a Path (argparse Action perhaps)
        # action='append',
        # nargs=1,
        dest="supernetwork",
        default="Pocono_TEST1",
    )
    parser.add_argument("--ql", help="QLat input data", dest="ql", default=None)

    return parser.parse_args()


ENV_IS_CL = False
if ENV_IS_CL:
    root = pathlib.Path("/", "content", "t-route")
elif not ENV_IS_CL:
    root = pathlib.Path("../..").resolve()
    # sys.path.append(r"../python_framework_v02")

    # TODO: automate compile for the package scripts
    sys.path.append("fast_reach")

## network and reach utilities
import troute.nhd_network_utilities_v02 as nnu
import mc_reach
import troute.nhd_network as nhd_network
import troute.nhd_io as nhd_io


def writetoFile(file, writeString):
    file.write(writeString)
    file.write("\n")


def constant_qlats(index_dataset, nsteps, qlat):
    q = np.full((len(index_dataset.index), nsteps), qlat, dtype="float32")
    ql = pd.DataFrame(q, index=index_dataset.index, columns=range(nsteps))
    return ql


def main():

    args = _handle_args()

    nts = args.nts
    debuglevel = -1 * args.debuglevel
    verbose = args.verbose
    showtiming = args.showtiming
    supernetwork = args.supernetwork
    break_network_at_waterbodies = args.break_network_at_waterbodies
    csv_output_folder = args.csv_output_folder
    assume_short_ts = args.assume_short_ts

    test_folder = pathlib.Path(root, "test")
    geo_input_folder = test_folder.joinpath("input", "geo")

    # TODO: Make these commandline args
    """##NHD Subset (Brazos/Lower Colorado)"""
    # supernetwork = 'Brazos_LowerColorado_Named_Streams'
    # supernetwork = 'Brazos_LowerColorado_ge5'
    # supernetwork = 'Pocono_TEST1'
    """##NHD CONUS order 5 and greater"""
    # supernetwork = 'CONUS_ge5'
    """These are large -- be careful"""
    # supernetwork = 'Mainstems_CONUS'
    # supernetwork = 'CONUS_FULL_RES_v20'
    # supernetwork = 'CONUS_Named_Streams' #create a subset of the full resolution by reading the GNIS field
    # supernetwork = 'CONUS_Named_combined' #process the Named streams through the Full-Res paths to join the many hanging reaches

    if verbose:
        print("creating supernetwork connections set")
    if showtiming:
        start_time = time.time()

    # STEP 1
    network_data = nnu.set_supernetwork_data(
        supernetwork=args.supernetwork,
        geo_input_folder=geo_input_folder,
        verbose=False,
        debuglevel=debuglevel,
    )

    cols = network_data["columns"]
    param_df = nhd_io.read(network_data["geo_file_path"])
    param_df = param_df[list(cols.values())]
    param_df = param_df.set_index(cols["key"])

    if "mask_file_path" in network_data:
        data_mask = nhd_io.read_mask(
            network_data["mask_file_path"],
            layer_string=network_data["mask_layer_string"],
        )
        param_df = param_df.filter(data_mask.iloc[:, network_data["mask_key"]], axis=0)

    param_df = param_df.sort_index()
    param_df = nhd_io.replace_downstreams(param_df, cols["downstream"], 0)

    if args.ql:
        qlats = nhd_io.read_qlat(args.ql)
    else:
        qlats = constant_qlats(param_df, nts, 10.0)

    # initial conditions, assume to be zero
    # TO DO: Allow optional reading of initial conditions from WRF
    q0 = pd.DataFrame(
        0, index=param_df.index, columns=["qu0", "qd0", "h0"], dtype="float32"
    )

    connections = nhd_network.extract_connections(param_df, cols["downstream"])
    wbodies = nhd_network.extract_waterbodies(
        param_df, cols["waterbody"], network_data["waterbody_null_code"]
    )

    if verbose:
        print("supernetwork connections set complete")
    if showtiming:
        print("... in %s seconds." % (time.time() - start_time))

    # STEP 2
    if showtiming:
        start_time = time.time()
    if verbose:
        print("organizing connections into reaches ...")

    rconn = nhd_network.reverse_network(connections)
    independent_networks = nhd_network.reachable_network(rconn)
    reaches_bytw = {}
    for tw, net in independent_networks.items():
        path_func = partial(nhd_network.split_at_junction, net)
        reaches_bytw[tw] = nhd_network.dfs_decomposition(net, path_func)

    if verbose:
        print("reach organization complete")
    if showtiming:
        print("... in %s seconds." % (time.time() - start_time))

    if showtiming:
        start_time = time.time()

    param_df["dt"] = 300.0
    param_df = param_df.rename(columns=nnu.reverse_dict(cols))
    param_df = param_df.astype("float32")

    # datasub = data[['dt', 'bw', 'tw', 'twcc', 'dx', 'n', 'ncc', 'cs', 's0']]

    parallel_compute_method = args.parallel_compute_method
    cpu_pool = args.cpu_pool
    compute_method = args.compute_method
    subnetwork_target_size = args.subnetwork_target_size
    if (not subnetwork_target_size) or (subnetwork_target_size <= 0):
        subnetwork_target_size = 1

    if compute_method == "standard cython compute network":
        compute_func = mc_reach.compute_network
    else:
        compute_func = mc_reach.compute_network

    if parallel_compute_method == "by-subnetwork-jit-clustered":
        networks_with_subnetworks_ordered_jit = nhd_network.build_subnetworks(
            connections, rconn, subnetwork_target_size
        )
        subnetworks_only_ordered_jit = defaultdict(dict)
        subnetworks = defaultdict(dict)
        for tw, ordered_network in networks_with_subnetworks_ordered_jit.items():
            intw = independent_networks[tw]
            for order, subnet_sets in ordered_network.items():
                subnetworks_only_ordered_jit[order].update(subnet_sets)
                for subn_tw, subnetwork in subnet_sets.items():
                    subnetworks[subn_tw] = {k: intw[k] for k in subnetwork}

        reaches_ordered_bysubntw = {}
        for order, ordered_subn_dict in subnetworks_only_ordered_jit.items():
            reaches_ordered_bysubntw[order] = {}
            for subn_tw, subnet in ordered_subn_dict.items():
                conn_subn = {k: connections[k] for k in subnet if k in connections}
                rconn_subn = {k: rconn[k] for k in subnet if k in rconn}
                path_func = partial(nhd_network.split_at_junction, rconn_subn)
                reaches_ordered_bysubntw[order][
                    subn_tw
                ] = nhd_network.dfs_decomposition(rconn_subn, path_func)

        cluster_threshold = 0.65  # When a job has a total segment count 65% of the target size, compute it
        # Otherwise, keep adding reaches.

        reaches_ordered_bysubntw_clustered = {}

        for order in subnetworks_only_ordered_jit:
            cluster = 0
            reaches_ordered_bysubntw_clustered[order] = {}
            reaches_ordered_bysubntw_clustered[order][cluster] = {
                "segs": [],
                "upstreams": {},
                "tw": [],
                "subn_reach_list": [],
            }
            for twi, (subn_tw, subn_reach_list) in enumerate(
                reaches_ordered_bysubntw[order].items(), 1
            ):
                segs = list(chain.from_iterable(subn_reach_list))
                reaches_ordered_bysubntw_clustered[order][cluster]["segs"].extend(segs)
                reaches_ordered_bysubntw_clustered[order][cluster]["upstreams"].update(
                    subnetworks[subn_tw]
                )

                reaches_ordered_bysubntw_clustered[order][cluster]["tw"].append(subn_tw)
                reaches_ordered_bysubntw_clustered[order][cluster][
                    "subn_reach_list"
                ].extend(subn_reach_list)

                if (
                    len(reaches_ordered_bysubntw_clustered[order][cluster]["segs"])
                    >= cluster_threshold * subnetwork_target_size
                ) and (
                    twi
                    < len(reaches_ordered_bysubntw[order])
                    # i.e., we haven't reached the end
                    # TODO: perhaps this should be a while condition...
                ):
                    cluster += 1
                    reaches_ordered_bysubntw_clustered[order][cluster] = {
                        "segs": [],
                        "upstreams": {},
                        "tw": [],
                        "subn_reach_list": [],
                    }

        if showtiming:
            print("JIT Preprocessing time %s seconds." % (time.time() - start_time))
            print("starting Parallel JIT calculation")

        start_para_time = time.time()
        # if 1 == 1:
        with Parallel(n_jobs=cpu_pool, backend="threading") as parallel:
            results_subn = defaultdict(list)
            flowveldepth_interorder = {}

            for order in range(max(subnetworks_only_ordered_jit.keys()), -1, -1):
                jobs = []
                for cluster, clustered_subns in reaches_ordered_bysubntw_clustered[
                    order
                ].items():
                    segs = clustered_subns["segs"]
                    offnetwork_upstreams = set()
                    segs_set = set(segs)
                    for seg in segs:
                        for us in rconn[seg]:
                            if us not in segs_set:
                                offnetwork_upstreams.add(us)

                    segs.extend(offnetwork_upstreams)
                    param_df_sub = param_df.loc[
                        segs, ["dt", "bw", "tw", "twcc", "dx", "n", "ncc", "cs", "s0"]
                    ].sort_index()
                    if order < max(subnetworks_only_ordered_jit.keys()):
                        for us_subn_tw in offnetwork_upstreams:
                            subn_tw_sortposition = param_df_sub.index.get_loc(
                                us_subn_tw
                            )
                            flowveldepth_interorder[us_subn_tw][
                                "position_index"
                            ] = subn_tw_sortposition
                    qlat_sub = qlats.loc[segs].sort_index()
                    q0_sub = q0.loc[segs].sort_index()
                    subn_reach_list = clustered_subns["subn_reach_list"]
                    upstreams = clustered_subns["upstreams"]

                    # results_subn[order].append(
                    #     compute_func(
                    jobs.append(
                        delayed(compute_func)(
                            nts,
                            subn_reach_list,
                            upstreams,
                            param_df_sub.index.values,
                            param_df_sub.columns.values,
                            param_df_sub.values,
                            qlat_sub.values,
                            q0_sub.values,
                            # flowveldepth_interorder,  # obtain keys and values from this dataset
                            {
                                us: fvd
                                for us, fvd in flowveldepth_interorder.items()
                                if us in offnetwork_upstreams
                            },
                        )
                    )
                results_subn[order] = parallel(jobs)

                if order > 0:  # This is not needed for the last rank of subnetworks
                    flowveldepth_interorder = {}
                    for ci, (cluster, clustered_subns) in enumerate(
                        reaches_ordered_bysubntw_clustered[order].items()
                    ):
                        for subn_tw in clustered_subns["tw"]:
                            # TODO: This index step is necessary because we sort the segment index
                            # TODO: I think there are a number of ways we could remove the sorting step
                            #       -- the binary search could be replaced with an index based on the known topology
                            flowveldepth_interorder[subn_tw] = {}
                            subn_tw_sortposition = (
                                results_subn[order][ci][0].tolist().index(subn_tw)
                            )
                            flowveldepth_interorder[subn_tw]["results"] = results_subn[
                                order
                            ][ci][1][subn_tw_sortposition]
                            # what will it take to get just the tw FVD values into an array to pass to the next loop?
                            # There will be an empty array initialized at the top of the loop, then re-populated here.
                            # we don't have to bother with populating it after the last group

        results = []
        for order in subnetworks_only_ordered_jit:
            results.extend(results_subn[order])

        if showtiming:
            print("PARALLEL TIME %s seconds." % (time.time() - start_para_time))

    elif parallel_compute_method == "by-subnetwork-jit":
        networks_with_subnetworks_ordered_jit = nhd_network.build_subnetworks(
            connections, rconn, subnetwork_target_size
        )
        subnetworks_only_ordered_jit = defaultdict(dict)
        subnetworks = defaultdict(dict)
        for tw, ordered_network in networks_with_subnetworks_ordered_jit.items():
            for order, subnet_sets in ordered_network.items():
                subnetworks_only_ordered_jit[order].update(subnet_sets)
                for subn_tw, subnetwork in subnet_sets.items():
                    for k in independent_networks[tw]:
                        if k in subnetwork:
                            subnetworks[subn_tw].update(
                                {k: independent_networks[tw][k]}
                            )

        reaches_bysubntw = {}
        for order, ordered_subn_dict in subnetworks_only_ordered_jit.items():
            reaches_bysubntw[order] = {}
            for subn_tw, subnet in ordered_subn_dict.items():
                conn_subn = {k: connections[k] for k in subnet if k in connections}
                rconn_subn = {k: rconn[k] for k in subnet if k in rconn}
                path_func = partial(nhd_network.split_at_junction, rconn_subn)
                reaches_bysubntw[order][subn_tw] = nhd_network.dfs_decomposition(
                    rconn_subn, path_func
                )

        if showtiming:
            print("JIT Preprocessing time %s seconds." % (time.time() - start_time))
            print("starting Parallel JIT calculation")

        start_para_time = time.time()
        with Parallel(n_jobs=cpu_pool, backend="threading") as parallel:
            results_subn = defaultdict(list)
            flowveldepth_interorder = {}

            for order in range(max(subnetworks_only_ordered_jit.keys()), -1, -1):
                jobs = []
                for twi, (subn_tw, subn_reach_list) in enumerate(
                    reaches_bysubntw[order].items(), 1
                ):
                    # TODO: Confirm that a list here is best -- we are sorting,
                    # so a set might be sufficient/better
                    segs = list(chain.from_iterable(subn_reach_list))
                    offnetwork_upstreams = set()
                    segs_set = set(segs)
                    for seg in segs:
                        for us in rconn[seg]:
                            if us not in segs_set:
                                offnetwork_upstreams.add(us)

                    segs.extend(offnetwork_upstreams)
                    param_df_sub = param_df.loc[
                        segs, ["dt", "bw", "tw", "twcc", "dx", "n", "ncc", "cs", "s0"]
                    ].sort_index()
                    if order < max(subnetworks_only_ordered_jit.keys()):
                        for us_subn_tw in offnetwork_upstreams:
                            subn_tw_sortposition = param_df_sub.index.get_loc(
                                us_subn_tw
                            )
                            flowveldepth_interorder[us_subn_tw][
                                "position_index"
                            ] = subn_tw_sortposition
                    qlat_sub = qlats.loc[segs].sort_index()
                    q0_sub = q0.loc[segs].sort_index()
                    jobs.append(
                        delayed(compute_func)(
                            nts,
                            subn_reach_list,
                            subnetworks[subn_tw],
                            param_df_sub.index.values,
                            param_df_sub.columns.values,
                            param_df_sub.values,
                            qlat_sub.values,
                            q0_sub.values,
                            # flowveldepth_interorder,  # obtain keys and values from this dataset
                            {
                                us: fvd
                                for us, fvd in flowveldepth_interorder.items()
                                if us in offnetwork_upstreams
                            },
                        )
                    )

                results_subn[order] = parallel(jobs)

                if order > 0:  # This is not needed for the last rank of subnetworks
                    flowveldepth_interorder = {}
                    for twi, subn_tw in enumerate(reaches_bysubntw[order]):
                        # TODO: This index step is necessary because we sort the segment index
                        # TODO: I think there are a number of ways we could remove the sorting step
                        #       -- the binary search could be replaced with an index based on the known topology
                        flowveldepth_interorder[subn_tw] = {}
                        subn_tw_sortposition = (
                            results_subn[order][twi][0].tolist().index(subn_tw)
                        )
                        flowveldepth_interorder[subn_tw]["results"] = results_subn[
                            order
                        ][twi][1][subn_tw_sortposition]
                        # what will it take to get just the tw FVD values into an array to pass to the next loop?
                        # There will be an empty array initialized at the top of the loop, then re-populated here.
                        # we don't have to bother with populating it after the last group

        results = []
        for order in subnetworks_only_ordered_jit:
            results.extend(results_subn[order])

        if showtiming:
            print("PARALLEL TIME %s seconds." % (time.time() - start_para_time))

    elif parallel_compute_method == "by-network":
        if showtiming:
            print("JIT Preprocessing time %s seconds." % (time.time() - start_time))
            print("starting Parallel JIT calculation")

        start_para_time = time.time()
        with Parallel(n_jobs=cpu_pool, backend="threading") as parallel:
            jobs = []
            for twi, (tw, reach_list) in enumerate(reaches_bytw.items(), 1):
                segs = list(chain.from_iterable(reach_list))
                param_df_sub = param_df.loc[
                    segs, ["dt", "bw", "tw", "twcc", "dx", "n", "ncc", "cs", "s0"]
                ].sort_index()
                qlat_sub = qlats.loc[segs].sort_index()
                q0_sub = q0.loc[segs].sort_index()
                jobs.append(
                    delayed(compute_func)(
                        nts,
                        reach_list,
                        independent_networks[tw],
                        param_df_sub.index.values,
                        param_df_sub.columns.values,
                        param_df_sub.values,
                        qlat_sub.values,
                        q0_sub.values,
                    )
                )
            results = parallel(jobs)

        if showtiming:
            print("PARALLEL TIME %s seconds." % (time.time() - start_para_time))

    else:  # Execute in serial
        results = []
        for twi, (tw, reach_list) in enumerate(reaches_bytw.items(), 1):
            segs = list(chain.from_iterable(reach_list))
            param_df_sub = param_df.loc[
                segs, ["dt", "bw", "tw", "twcc", "dx", "n", "ncc", "cs", "s0"]
            ].sort_index()
            qlat_sub = qlats.loc[segs].sort_index()
            q0_sub = q0.loc[segs].sort_index()
            results.append(
                compute_func(
                    nts,
                    reach_list,
                    independent_networks[tw],
                    param_df_sub.index.values,
                    param_df_sub.columns.values,
                    param_df_sub.values,
                    qlat_sub.values,
                    q0_sub.values,
                )
            )

    if (debuglevel <= -1) or csv_output_folder:
        qvd_columns = pd.MultiIndex.from_product(
            [range(nts), ["q", "v", "d"]]
        ).to_flat_index()
        flowveldepth = pd.concat(
            [pd.DataFrame(d, index=i, columns=qvd_columns) for i, d in results],
            copy=False,
        ).sort_index()

        if csv_output_folder:
            flowveldepth = flowveldepth.sort_index()
            output_path = pathlib.Path(csv_output_folder).resolve()
            flowveldepth.to_csv(output_path.joinpath(f"{args.supernetwork}.csv"))

        if debuglevel <= -1:
            print(flowveldepth)

    if verbose:
        print("ordered reach computation complete")
    if showtiming:
        print("... in %s seconds." % (time.time() - start_time))


if __name__ == "__main__":
    main()
