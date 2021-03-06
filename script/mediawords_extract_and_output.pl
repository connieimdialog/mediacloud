#!/usr/bin/env perl

# extract and output download / file

use strict;
use warnings;

BEGIN
{
    use FindBin;
    use lib "$FindBin::Bin/../lib";
}

use Modern::Perl "2015";
use MediaWords::CommonLibs;

use Getopt::Long;
use HTML::Strip;
use DBIx::Simple::MediaWords;
use MediaWords::DB;

use MediaWords::DBI::Downloads;
use MediaWords::DBI::DownloadTexts;
use Readonly;
use List::Util qw(first max maxstr min minstr reduce shuffle sum);
use XML::LibXML;
use Data::Dumper;

use Digest::SHA qw(sha1 sha1_hex sha1_base64);

#use XML::LibXML::CDATASection;
use Encode;
use MIME::Base64;
use MediaWords::Languages::en;

#use XML::LibXML::Enhanced;

my $_re_generate_cache = 0;

sub store_preprocessed_result
{
    my ( $download, $preprocessed_lines, $extract_results, $content_ref, $story ) = @_;

    INFO "starting store_preprocessed_result";
    INFO "downloads_id: " . $download->{ downloads_id };
    INFO "STORY GUID $story->{ guid }";
    INFO "STORY GUID $story->{ title }";
    my $lines_concated = join "", map { $_ . "\n" } @{ $preprocessed_lines };

    INFO "Preprocessed_lines:";

    #MediaWords::DBI::DownloadTexts::update_extractor_results_with_text_and_html( $extract_results );

    INFO "EXTRACTED HTML $extract_results->{ extracted_html }";
    INFO "EXTRACTED TEXT $extract_results->{ extracted_text }";

    INFO "Starting get_sentences ";
    my $lang = MediaWords::Languages::en->new();
    my $sentences = $lang->get_sentences( $extract_results->{ extracted_text } ) || return;

    INFO "Finished get_sentences ";

    say Dumper( $sentences );

    return;
}

sub store_downloads
{

    my $downloads = shift;

    my @downloads = @{ $downloads };

    INFO "Starting store_downloads";

    @downloads = sort { $a->{ downloads_id } <=> $b->{ downloads_id } } @downloads;

    my $download_results = [];

    my $dbs = MediaWords::DB::connect_to_db;

    for my $download ( @downloads )
    {
        INFO "Processing download $download->{downloads_id}";

        my $preprocessed_lines = MediaWords::DBI::Downloads::fetch_preprocessed_content_lines( $dbs, $download );
        my $extract_results = MediaWords::DBI::Downloads::extract( $dbs, $download );

        INFO "Got extract_results:\n " . Dumper( $extract_results );

        my $content_ref = MediaWords::DBI::Downloads::fetch_content( $dbs, $download );

        my $story = $dbs->query( "select * from stories where stories_id = ?", $download->{ stories_id } )->hash;

        store_preprocessed_result( $download, $preprocessed_lines, $extract_results, $content_ref, $story );
    }

}

# do a test run of the text extractor
sub main
{

    my $dbs = MediaWords::DB::connect_to_db;

    my $file;
    my @download_ids;

    GetOptions(
        'file|f=s'                  => \$file,
        'downloads|d=s'             => \@download_ids,
        'regenerate_database_cache' => \$_re_generate_cache,
    ) or die;

    unless ( $file || ( @download_ids ) )
    {
        die "no options given ";
    }

    my $downloads;

    INFO join( ' ', @download_ids );

    if ( @download_ids )
    {
        $downloads = $dbs->query( "SELECT * from downloads where downloads_id in (??)", @download_ids )->hashes;
    }
    elsif ( $file )
    {
        open( DOWNLOAD_ID_FILE, $file ) || die( "Could not open file: $file" );
        @download_ids = <DOWNLOAD_ID_FILE>;
        $downloads = $dbs->query( "SELECT * from downloads where downloads_id in (??)", @download_ids )->hashes;
    }
    else
    {
        die "must specify file or downloads id";
    }

    INFO Dumper( $downloads );

    die 'no downloads found ' unless scalar( @$downloads );

    INFO scalar( @$downloads ) . ' downloads';
    store_downloads( $downloads );
}

main();
