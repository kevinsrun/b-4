# Invoke only pretrained ampir models. Stdout/output use simple machine-readable TSV.
args <- commandArgs(trailingOnly=TRUE)
if (length(args) == 1 && args[1] == "--probe") {
    cat("R\t", as.character(getRversion()), "\n", sep="")
    for (pkg in c("ampir", "caret", "kernlab", "Peptides", "Rcpp", "e1071")) {
        cat(pkg, "\t", as.character(packageVersion(pkg)), "\n", sep="")
    }
    quit(status=0)
}
if (length(args) != 3 || !(args[3] %in% c("mature", "precursor"))) {
    stop("usage: ampir_worker.R input.fasta output.tsv mature|precursor")
}
suppressPackageStartupMessages(library(ampir))
input <- ampir::read_faa(args[1])
result <- ampir::predict_amps(input, min_len=10, n_cores=1, model=args[3])
write.table(result[, c("seq_name", "prob_AMP")], args[2], sep="\t",
            row.names=FALSE, quote=FALSE, na="NA")
