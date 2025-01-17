import gc
import os
import numpy as np
from collections import Counter
import scanpy as sc
from sklearn.metrics import adjusted_rand_score
from sklearn.metrics.cluster import normalized_mutual_info_score
import time
import pandas as pd
import sys
from scipy.sparse import csr_matrix
from multiprocessing.pool import ThreadPool as Pool
from functools import partial
sys.path.append("..")

from secuer.secuer import (secuer, Tcut_for_bipartite_graph, Logger)
logg = Logger()

def secuerconsensus(fea,
                    k=None,
                    run_secuer=True,
                    M=5,
                    p=1000,
                    Knn=5,
                    multiProcessState=False,
                    num_multiProcesses=4):
    '''
     Perform the consensus function.
    :params fea: A expression matrix with cells by genes or a clustering result with cells by clusters.
    :params k: int, default=None. The number of clusters, automatically estimated if None.
    :params run_secuer: bool, default=True. Call secuer to use the ensemble to get the final result, if the input fea is
            the clustering result obtained by different methods, set it to False.
    :params M: int, default=5. The number of consensus times.
    :params p: int, default=1000:. The number of representatives using in secuer.
    :params Knn: int, default=5. default=5: The k nearest neighbors using in secuer.
    :param multiProcessState: bool, default=False. Whether to use parallel. Recommend to default by False.
    :param num_multiProcesses: int, default=4. The number of parallel processes.
    :return: 1D-array. The labels for each cell.
    '''
    baseCls, ks = secuerC_EnsembleGeneration(fea=fea, M=M, p=p,
                                             Knn=Knn,
                                             run_secuer=run_secuer,
                                             multiProcessState=multiProcessState,
                                             num_multiProcesses=num_multiProcesses)
    print('Performing the consensus function...')
    if not k:
        k=Counter(ks).most_common(1)[0][0]
    L = secuerC_ConsensusFunction(baseCls, k)
    return L

def Multi_secuer(fea, p, Knn, resolution, distance1,maxTcutKmIters=1, cntTcutKmReps=5,j = 0):
    logg.info(f'Running secuer {j + 1}')
    res, ks = secuer(fea=fea,
                     eskMethod='subGraph',
                     eskResolution = resolution[j],
                     mode='Consensus',
                     distance = distance1[j],
                     p = p,
                     Knn=Knn,
                     maxTcutKmIters=maxTcutKmIters,
                     cntTcutKmReps=cntTcutKmReps,
                     seed = j)
    return res, ks

# random_rep=True,adj_param=False can remove
def secuerC_EnsembleGeneration(fea,
                               M,
                               p=1000,
                               Knn=5,
                               run_secuer=True,
                               multiProcessState=False,
                               num_multiProcesses=4):
    '''
    Cluster cell using SecuerConsensus.
    :param fea: A expression matrix with cell by gene or a matrix with multiple clustering results by other methods.
    :param p: int, default=1000. The number of anchors.
    :param knn: int, default=5. The number of neighbors of anchors for each cell.
    :param run_secuer: default=True. True if fea is a expression matrix. False if fea is a matrix with multiple clustering results.

    :param multiProcessState: bool, default=False. whether use the multiple process.

    :param num_multiProcesses: int, default=4. The number of threadPool.
    :return:The pSize cluster centers as the final representatives.
    '''
    N = fea.shape[0]
    if p > N:
        p = N

    tcutKmIters = 5
    tcutKmRps = 1
    if N < 1000:
        resolution = [float(i / 10) for i in range(1, M + 1)]
    else:
        if M < 11:
            resolution = [float(i / 10) for i in range(2, M*2+1, 2)]
        elif  M >= 11 and M < 21:
            resolution = [float(i / 10) for i in range(2, M+2)]
        else:
            np.random.seed(1)
            resolution = np.random.choice([float(i / 10) for i in range(1, M+1)],M)
    # resolution = [float(i / 10) for i in range(1, M + 1)]
    np.random.seed(1) # set random seet
    distance1 = np.random.choice(['euclidean', 'cosine'], M)
    if run_secuer:
        members = []
        k = []
        if multiProcessState == False:
            for j in range(M):
                logg.info(f'Running secuer {j + 1}')
                res, ks = secuer(fea=fea, eskMethod='subGraph',
                                 eskResolution=resolution[j], mode='Consensus',
                                 distance=distance1[j], p=p, Knn=Knn,
                                 maxTcutKmIters=tcutKmIters, cntTcutKmReps=tcutKmRps,
                                 seed=j)
                members += [res.tolist()]
                k += [ks]
            members = np.array(members).T
        else:
            pool = Pool(num_multiProcesses)
            func = partial(Multi_secuer, fea, p, Knn, resolution, distance1,
                           tcutKmIters,tcutKmRps)
            outputs = pool.map(func, np.arange(M))
            for i in range(M):
                members += [outputs[i][0].tolist()]
                k += [outputs[i][1]]
            members = np.array(members).T
    else:
        members = fea

    return members, k  # N by M cluster

def secuerC_ConsensusFunction(baseCls, k,
                            maxTcutKmIters=100, cntTcutKmReps=3):
    # Combine the M base clusterings in baseCls to obtain the final clustering
    # result (with k clusters).
    N, M = baseCls.shape
    maxCls = np.max(baseCls, axis=0) + 1
    # print(f'k:{k},maxCls:{maxCls}')
    maxCls = np.cumsum(maxCls)
    baseCls = baseCls + np.concatenate([[0], maxCls[0:-1]])
    cntCls = maxCls[-1]
    # Build the bipartite graph.
    indptr = np.arange(0, N * M + 1, M)
    B = csr_matrix(([1] * N * M,  # copy the data, otherwise strange behavior here
                     baseCls.copy().ravel(), indptr.copy().ravel()), shape=(N, cntCls))
    # print(B.shape)
    del baseCls
    gc.collect()
    colB = np.sum(B, axis=0)
    B = B[:, (np.array(colB).flatten()) != 0]
    # Cut the bipartite graph.
    labels,ks = Tcut_for_bipartite_graph(B, k,eskMethod='subGraph',
                                      maxKmIters=maxTcutKmIters,
                                      cntReps = cntTcutKmReps)
    return labels

if __name__ == '__main__':
    file = 'gold_label_data/'
    files = os.listdir(file)
    fileh5sd_gold = [i for i in files if i.endswith('.h5ad')]
    fileh5sd_gold
    nmi_secuerC = []
    ari_secuerC = []
    t_secuerC = []
    for i in range(len(fileh5sd_gold)):
        print(fileh5sd_gold[i])
        data = sc.read(file + fileh5sd_gold[i])
        fea = data.obsm['X_pca']
        start = time.time()
        try:
            sc.pp.neighbors(data,n_pcs=48)
        except:
            sc.pp.neighbors(data, n_pcs=50)
        res,k = secuerconsensus(run_secuer=True,
                                fea= fea,
                                Knn=5,
                                M=5,
                                multiProcessState=True,
                                num_multiProcesses=4)
        print(np.unique(res).shape[0])
        end = time.time() - start
        print(np.unique(res).shape[0],np.unique(data.obs['celltype']).shape[0])
        name_up = 'secuerC_lable_' + str(i)
        data.obs[name_up] = pd.Categorical(res)
        nmi_secuerC.append(normalized_mutual_info_score(data.obs['celltype'], res))
        ari_secuerC.append(adjusted_rand_score(data.obs['celltype'], res))
        t_secuerC.append(end)
        print()
    res_secuerC = pd.DataFrame([t_secuerC, nmi_secuerC, ari_secuerC],
                             index=['t_secuerC', 'nmi_secuerC', 'ari_secuerC'],
                             columns=fileh5sd_gold)
    print(res_secuerC.values)
