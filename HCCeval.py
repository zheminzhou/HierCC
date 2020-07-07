#!/usr/bin/env python

import sys, pandas as pd, numpy as np, logging, sysv_ipc
import argparse
from sklearn.metrics import silhouette_score, normalized_mutual_info_score
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as colors
from multiprocessing import Pool
try :
    from getDistance import getDistance
except :
    from .getDistance import getDistance

logging.basicConfig(format='%(asctime)s | %(message)s',stream=sys.stdout, level=logging.INFO)


def get_similarity2(data) :
    method, cc1, cc2 = data
    if np.unique(cc1).size == 1 and  np.unique(cc1).size == 1 :
        return 1.
    return method(cc1, cc2)

def get_similarity(method, cluster, stepwise, pool) :
    logging.info('Calculating NMIs...')
    similarity = np.ones([cluster.shape[1], cluster.shape[1]], dtype=np.float64)
    for i1, cc1 in enumerate(cluster.T) :
        if i1 % 10 == 0 :
            logging.info('    NMIs between level {0} and greater levels'.format(i1 * stepwise))
        similarity[i1, i1+1:] = pool.map(get_similarity2, [ [method, cc1, cc2] for cc2 in cluster.T[i1+1:] ])
        similarity[i1+1:, i1] = similarity[i1, i1+1:]
    similarity[similarity>0.999] = 0.999
    similarity[similarity<0.0] = 0.0
    return similarity

def get_silhouette(profile, cluster, stepwise, pool) :
    logging.info('Calculating pairwise distance ...')
    with getDistance(profile, 'p_dist', pool) as dist :
        dist.dist += dist.dist.T
        logging.info('Calculating Silhouette score ...')
        silhouette = np.array(pool.map(get_silhouette2, [ [dist.dist_buf.key, dist.dist.shape, tag] for tag in cluster.T ]))
    return silhouette

def get_silhouette2(data) :
    dist_key, dist_shape, tag = data
    s = np.unique(tag)
    if 2 <= s.size < tag.shape[0] :
        dist_buf = sysv_ipc.SharedMemory(dist_key)
        dist = np.ndarray(dist_shape, dtype=np.int32, buffer=memoryview(dist_buf))
        ss = silhouette_score(dist.astype(float), tag, metric = 'precomputed')
        dist_buf.detach()
        return ss
    else :
        return 0.

def get_args(args) :
    parser = argparse.ArgumentParser(description='''evalHCC evaluates HierCC results using varied statistic summaries.''', formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-p', '--profile', help='[INPUT; REQUIRED] name of the profile file. Can be GZIPed.', required=True)
    parser.add_argument('-c', '--cluster', help='[INPUT; REQUIRED] name of the hierCC file. Can be GZIPed.', required=True)
    parser.add_argument('-o', '--output', help='[OUTPUT; REQUIRED] Prefix for the output files.', required=True)
    parser.add_argument('-s', '--stepwise', help='[DEFAULT: 10] Evaluate every <stepwise> levels.', default=10, type=int)

    return parser.parse_args(args)    

def prepare_mat(profile_file) :
    mat = pd.read_csv(profile_file, sep='\t', header=None, dtype=str).values
    allele_columns = np.array([i == 0 or (not h.startswith('#')) for i, h in enumerate(mat[0])])
    mat = mat[1:, allele_columns].astype(int)
    mat = mat[mat.T[0]>0]
    return mat


def evalHCC(args) :
    args = get_args(args)
    pool = Pool(10)

    profile = prepare_mat(args.profile)
    cluster = prepare_mat(args.cluster)

    idx = { p:i for i, p in enumerate(profile.T[0])}
    cluster_idx = sorted([ [idx.get(c, -1), i] for i, c in enumerate(cluster.T[0]) if c in idx ])
    cluster = cluster[np.array(cluster_idx).T[1]]
    assert cluster.shape[0] == profile.shape[0], 'some profiles do not have corresponding cluster info'
    cluster = cluster[:, 1::args.stepwise]

    silhouette = get_silhouette(profile, cluster, args.stepwise, pool)
    similarity = get_similarity(normalized_mutual_info_score, cluster, args.stepwise, pool)

    #np.savez_compressed('test.npz', silhouette=silhouette, similarity=similarity)
    #data = np.load('test.npz')
    #silhouette, similarity = data['silhouette'], data['similarity']

    with open(args.output+'.tsv', 'w') as fout:
        levels = ['HC{0}'.format(lvl*args.stepwise) for lvl in np.arange(silhouette.shape[0])]
        for lvl, ss in zip(levels, silhouette) :
            fout.write('#Silhouette\t{0}\t{1}\n'.format(lvl, ss))

        fout.write('\n#NMI\t{0}\n'.format('\t'.join(levels)))
        for lvl, nmis in zip(levels, similarity):
            fout.write('{0}\t{1}\n'.format(lvl, '\t'.join([ '{0:.3f}'.format(nmi) for nmi in nmis ])))
    fig, axs = plt.subplots(2, 2, #sharex='col', \
                            figsize=(8, 12), \
                            gridspec_kw={'width_ratios':(12, 1),
                                         'height_ratios': (65, 35)})

    heatplot = axs[0, 0].imshow( (10*(np.log10(1-similarity))), \
                                norm=colors.TwoSlopeNorm(vmin=-30., vcenter=-10., vmax=0), \
                                cmap = 'RdBu',\
                                extent=[0, silhouette.shape[0]*args.stepwise, \
                                        silhouette.shape[0]*args.stepwise, 0])
    cb = fig.colorbar(heatplot, cax=axs[0, 1])
    axs[1, 0].plot(np.arange(silhouette.shape[0])*args.stepwise, silhouette,)
    axs[1, 0].set_xlim([0, silhouette.shape[0]*args.stepwise])
    axs[1, 1].remove()
    axs[0, 0].set_ylabel('HCs (allelic distances)')
    axs[0, 0].set_xlabel('HCs (allelic distances)')
    axs[1, 0].set_ylabel('Silhouette scores')
    axs[1, 0].set_xlabel('HCs (allelic distances)')
    cb.set_label('Normalized Mutual Information')
    cb.set_ticks([-30, -23.01, -20, -13.01, -10, -3.01, 0])
    cb.ax.set_yticklabels(['>=.999', '.995', '.99', '.95', '.9', '.5', '.0'])
    plt.savefig(args.output+'.pdf')
    logging.info('Tab delimited evaluation is save in {0}.tsv'.format(args.output))
    logging.info('Graphic visualisation is save in {0}.pdf'.format(args.output))

if __name__ == '__main__' :
    evalHCC(sys.argv[1:])