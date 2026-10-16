#!/usr/bin/perl
use strict;
use warnings;
use LWP::UserAgent;

# 1. Primary NASA URLs (Direct links to files)
my %primary_map = (
    "ap240602.html"     => "https://apod.nasa.gov/apod/ap240602.html",
);

# 2. Fallback Base URLs
my %fallback_map = (
    "ap240602.html"     => "https://www.youtube.com/watch?v=sNUNB6CMnE8",
);

my $filename = $ENV{'QUERY_STRING'} || "";

if (exists $primary_map{$filename}) {
    my $ua = LWP::UserAgent->new;
    $ua->timeout(5); 
    
    # Check if NASA file is alive
    my $response = $ua->head($primary_map{$filename});

    if ($response->is_success) {
        # Success: Redirect to NASA
        redirect_to($primary_map{$filename});
    } else {
        # Failure: Construct fallback URL
        redirect_to($fallback_map{$filename});
    }
} else {
    print "Status: 404 Not Found\n";
    print "Content-type: text/plain\n\n";
    print "Movie not found.";
}

sub redirect_to {
    my ($url) = @_;
    print "Status: 307 Temporary Redirect\n";
    print "Location: $url\n\n";
    exit;
}

