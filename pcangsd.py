"""
PCAngsd Framework: Population genetic analyses for NGS data using PCA. Main caller.
"""

__author__ = "Jonas Meisner"

# Import functions
from helpFunctions import *
from emMAF import *
from covariance import *
from callGeno import *
from emInbreed import *
from emInbreedSites import *
from kinship import *
from selection import *
from admixture import *

# Import libraries
import argparse
import numpy as np
import pandas as pd
from numba import vectorize, boolean, float32

@vectorize([boolean(float32)])
def masking(x):
	return (x > 0.05) & (x < 0.95)


##### Argparse #####
parser = argparse.ArgumentParser(prog="PCAngsd")
parser.add_argument("--version", action="version", version="%(prog)s 0.8")
parser.add_argument("-beagle", metavar="FILE", 
	help="Input file of genotype likelihoods in Beagle format")
parser.add_argument("-n", metavar="INT", type=int,
	help="Number of individuals")
parser.add_argument("-iter", metavar="INT", type=int, default=100,
	help="Maximum iterations for covariance estimation (100)")
parser.add_argument("-tole", metavar="FLOAT", type=float, default=5e-5,
	help="Tolerance for covariance matrix estimation update (5e-5)")
parser.add_argument("-maf_iter", metavar="INT", type=int, default=200,
	help="Maximum iterations for population allele frequencies estimation - EM (200)")
parser.add_argument("-maf_tole", metavar="FLOAT", type=float, default=5e-5,
	help="Tolerance for population allele frequencies estimation update - EM (5e-5)")
parser.add_argument("-e", metavar="INT", type=int, default=0,
	help="Manual selection of eigenvectors used for linear regression")
parser.add_argument("-geno", metavar="FLOAT", type=float,
	help="Call genotypes from posterior probabilities using individual allele frequencies as prior")
parser.add_argument("-genoInbreed", metavar="FLOAT", type=float,
	help="Call genotypes from posterior probabilities using individual allele frequencies and inbreeding coefficients as prior")
parser.add_argument("-inbreed", metavar="INT", type=int,
	help="Compute the per-individual inbreeding coefficients by specified model")
parser.add_argument("-inbreedSites", action="store_true",
	help="Compute the per-site inbreeding coefficients by specified model and LRT")
parser.add_argument("-inbreed_iter", metavar="INT", type=int, default=200,
	help="Maximum iterations for inbreeding coefficients estimation - EM (200)")
parser.add_argument("-inbreed_tole", metavar="FLOAT", type=float, default=5e-5,
	help="Tolerance for inbreeding coefficients estimation update - EM (5e-5)")
parser.add_argument("-selection", metavar="INT", type=int,
	help="Compute a selection scan using the top principal components by specified model")
parser.add_argument("-kinship", action="store_true",
	help="Estimate the kinship matrix")
parser.add_argument("-admix", action="store_true",
	help="Estimate admixture proportions")
parser.add_argument("-admix_alpha", metavar="FLOAT-LIST", type=float, nargs="+", default=[0],
	help="L1-regularization factor in NMF for sparseness in Q")
parser.add_argument("-admix_seed", metavar="INT-LIST", type=int, nargs="+", default=[0],
	help="Random seed for admixture estimation")
parser.add_argument("-admix_iter", metavar="INT", type=int, default=100,
	help="Maximum iterations for admixture proportions estimation - NMF (100)")
parser.add_argument("-admix_tole", metavar="FLOAT", type=float, default=1e-5,
	help="Tolerance for admixture estimation update - EM (1e-5)")
parser.add_argument("-admix_batch", metavar="INT", type=int, default=20,
	help="Number of batches used for stochastic gradient descent (20)")
parser.add_argument("-admix_save", action="store_true",
	help="Save population-specific allele frequencies from admixture estimation")
parser.add_argument("-freq_save", action="store_true",
	help="Save estimated allele frequencies as files")
parser.add_argument("-sites_save", action="store_true",
	help="Save marker IDs of filtered sites")
parser.add_argument("-threads", metavar="INT", type=int, default=1)
parser.add_argument("-o", metavar="OUTPUT", help="Prefix output file name", default="pcangsd")
args = parser.parse_args()

print "Running PCAngsd with " + str(args.threads) + " thread(s)"
assert (args.beagle != None), "Missing Beagle file! (-beagle)"
assert (args.n != None), "Specify number of individuals! (-n)"

# Setting up workflow parameters
param_call = False
param_inbreed = False
param_inbreedSites = False
param_selection = False
param_kinship = False

if args.inbreed != None:
	param_inbreed = True
	if args.inbreed == 3:
		param_kinship = True

if args.inbreedSites:
	param_inbreedSites = True

if args.selection != None:
	param_selection = True

if args.kinship:
	param_kinship = True

if args.geno != None:
	param_call = True

if args.genoInbreed != None:
	assert param_inbreed, "Inbreeding coefficients must be estimated in order to use -genoInbreed! Use -inbreed parameter!"


# Parse Beagle file
print "Parsing Beagle file"
likeMatrix = pd.read_csv(str(args.beagle), sep="\t", engine="c", header=0, usecols=range(3, 3 + 3*args.n), dtype=np.float32)
likeMatrix = likeMatrix.as_matrix().T


##### Estimate population allele frequencies #####
print "\n" + "Estimating population allele frequencies"
f = alleleEM(likeMatrix, args.maf_iter, args.maf_tole, args.threads)
mask = masking(f)
print "Number of sites evaluated: " + str(np.sum(mask))

# Update arrays
f = np.compress(mask, f)
likeMatrix = np.compress(mask, likeMatrix, axis=1)


##### PCAngsd #####
print "\n" + "Estimating covariance matrix"	
C, indf, nEV, expG = PCAngsd(likeMatrix, args.e, args.iter, f, args.tole, args.threads)

# Create and save data frames
pd.DataFrame(C).to_csv(str(args.o) + ".cov", sep="\t", header=False, index=False)
print "Saved covariance matrix as " + str(args.o) + ".cov"


##### Selection scan #####
if param_selection and args.selection == 1:
	print "\n" + "Performing selection scan using FastPCA method"

	# Perform selection scan and save data frame
	chisqDF = pd.DataFrame(selectionScan(expG, f, C, nEV, model=1, threads=args.threads).T)
	chisqDF.to_csv(str(args.o) + ".selection.gz", sep="\t", header=False, index=False, compression="gzip")
	print "Saved selection statistics for the top PCs as " + str(args.o) + ".selection.gz"

	# Release memory
	del chisqDF

elif param_selection and args.selection == 2:
	print "\n" + "Performing selection scan using PCAdapt method"

	# Perform selection scan and save data frame
	mahalanobisDF = pd.DataFrame(selectionScan(expG, f, C, nEV, model=2, threads=args.threads))
	mahalanobisDF.to_csv(str(args.o) + ".selection.gz", sep="\t", header=False, index=False, compression="gzip")
	print "Saved selection statistics for the top PCs as " + str(args.o) + ".selection.gz"

	# Release memory
	del mahalanobisDF


##### Kinship estimation #####
if param_kinship:
	print "\n" + "Estimating kinship matrix"

	# Perform kinship estimation
	phi = kinshipConomos(likeMatrix, indf)
	pd.DataFrame(phi).to_csv(str(args.o) + ".kinship", sep="\t", header=False, index=False)
	print "Saved kinship matrix as " + str(args.o) + ".kinship"


##### Individual inbreeding coefficients #####
if param_inbreed and args.inbreed == 1:
	print "\n" + "Estimating inbreeding coefficients using maximum likelihood estimator (EM)"

	# Estimating inbreeding coefficients
	F = inbreedEM(likeMatrix, indf, 1, args.inbreed_iter, args.inbreed_tole)
	pd.DataFrame(F).to_csv(str(args.o) + ".inbreed", sep="\t", header=False, index=False)
	print "Saved inbreeding coefficients as " + str(args.o) + ".inbreed"

elif param_inbreed and args.inbreed == 2:
	print "\n" + "Estimating inbreeding coefficients using Simple estimator (EM)"

	# Estimating inbreeding coefficients
	F = inbreedEM(likeMatrix, indf, 2, args.inbreed_iter, args.inbreed_tole)
	pd.DataFrame(F).to_csv(str(args.o) + ".inbreed", sep="\t", header=False, index=False)
	print "Saved inbreeding coefficients as " + str(args.o) + ".inbreed"
	
elif param_inbreed and args.inbreed == 3 and param_kinship:
	print "\n" + "Estimating inbreeding coefficients using kinship estimator (PC-Relate)"

	# Estimating inbreeding coefficients by previously estimated kinship matrix
	F = 2*phi.diagonal() - 1
	pd.DataFrame(F).to_csv(str(args.o) + ".inbreed", sep="\t", header=False, index=False)
	print "Saved inbreeding coefficients as " + str(args.o) + ".inbreed"

	# Release memory
	del phi


##### Per-site inbreeding coefficients #####
if param_inbreedSites:
	print "\n" + "Estimating per-site inbreeding coefficients using simple estimator (EM) and performing LRT"

	# Estimating per-site inbreeding coefficients
	Fsites, lrt = inbreedSitesEM(likeMatrix, indf, args.inbreed_iter, args.inbreed_tole)

	# Save data frames
	Fsites_DF = pd.DataFrame(Fsites)
	Fsites_DF.to_csv(str(args.o) + ".inbreedSites.gz", sep="\t", header=False, index=False, compression="gzip")
	print "Saved per-site inbreeding coefficients as " + str(args.o) + ".inbreedSites.gz"

	lrt_DF = pd.DataFrame(lrt)
	lrt_DF.to_csv(str(args.o) + ".lrtSites.gz", sep="\t", header=False, index=False, compression="gzip")
	print "Saved likelihood ratio tests as " + str(args.o) + ".lrtSites.gz"

	# Release memory
	del Fsites
	del Fsites_DF
	del lrt
	del lrt_DF


##### Genotype calling #####
if param_call:
	print "\n" + "Calling genotypes with a threshold of " + str(args.geno)

	# Call genotypes and save data frame
	genotypesDF = pd.DataFrame(callGeno(likeMatrix, indf, None, args.geno, args.threads).T)
	genotypesDF.to_csv(str(args.o) + ".geno.gz", "\t", header=False, index=False, compression="gzip")
	print "Saved called genotypes as " + str(args.o) + ".geno.gz"

	# Release memory
	del genotypesDF

elif args.genoInbreed != None:
	print "\n" + "Calling genotypes with a threshold of " + str(args.genoInbreed)

	# Call genotypes and save data frame
	genotypesDF = pd.DataFrame(callGeno(likeMatrix, indf, F, args.genoInbreed, args.threads).T)
	genotypesDF.to_csv(str(args.o) + ".genoInbreed.gz", "\t", header=False, index=False, compression="gzip")
	print "Saved called genotypes as " + str(args.o) + ".genoInbreed.gz"

	# Release memory
	del genotypesDF


##### Optional save #####

# Save updated marker IDs
if args.sites_save:
	pos = pd.read_csv(str(args.beagle), sep="\t", engine="c", header=0, usecols=[0])
	pos = pos.ix[mask]
	pos.to_csv(str(args.o) + ".sites", header=False, index=False)
	print "Saved site IDs as " + str(args.o) + ".sites"
	del pos
	del mask

if args.freq_save:
	pd.DataFrame(f).to_csv(str(args.o) + ".mafs.gz", header=False, index=False, compression="gzip")
	print "Saved population allele frequencies as " + str(args.o) + ".mafs.gz"

	pd.DataFrame(indf.T).to_csv(str(args.o) + ".indmafs.gz", sep="\t", header=False, index=False, compression="gzip")
	print "Saved individual allele frequencies as " + str(args.o) + ".indmafs.gz"

del likeMatrix
del f
del expG


##### Admixture proportions #####
if args.admix:
	K = nEV + 1
	for a in args.admix_alpha:
		for s in args.admix_seed:
			print "\n" + "Estimating admixture using NMF with K=" + str(K) + ", alpha=" + str(a) + " and seed=" + str(s)
			Q_admix, F_admix = admixNMF(indf, K, C, a, args.admix_iter, args.admix_tole, s, args.admix_batch, args.threads)

			# Save data frame
			pd.DataFrame(Q_admix).to_csv(str(args.o) + ".K" + str(K) + ".a" + str(a) + ".s" + str(s) + ".qopt", sep="\t", header=False, index=False)
			print "Saved admixture proportions as " + str(args.o) + ".K" + str(K) + ".a" + str(a) + ".s" + str(s) + ".qopt"

			if args.admix_save:
				pd.DataFrame(F_admix).to_csv(str(args.o) + ".K" + str(K) + ".a" + str(a) + ".s" + str(s) + ".fopt.gz", sep="\t", header=False, index=False, compression="gzip")
				print "Saved population-specific allele frequencies as " + str(args.o) + ".K" + str(K) + ".a" + str(a) + ".fopt.gz"

			# Release memory
			del Q_admix
			del F_admix