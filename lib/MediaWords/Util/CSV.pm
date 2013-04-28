package MediaWords::Util::CSV;
use Modern::Perl "2012";
use MediaWords::CommonLibs;

use strict;

use Encode;
use Text::CSV_XS;

# various functions for outputting csv

# return an encoded csv file representing a list of hashes.
# if $fields is specified, use it as a list of field names and
# dump the fields in the specified order.  otherwise, just
# get the field names from the hash in the first row (with
# semi-random order)
sub get_hashes_as_encoded_csv
{
    my ( $hashes, $fields ) = @_;

    my $output = '';
    if ( @{ $hashes } )
    {
        my $csv = Text::CSV_XS->new( { binary => 1 } );

        my $keys = $fields || [ keys( %{ $hashes->[ 0 ] } ) ];
        $csv->combine( @{ $keys } );

        $output .= $csv->string . "\n";

        for my $hash ( @{ $hashes } )
        {
            $csv->combine( map { $hash->{ $_ } } @{ $keys } );

            $output .= $csv->string . "\n";
        }
    }

    my $encoded_output = Encode::encode( 'utf-8', $output );

    return $encoded_output;
}

# send a list of hashes as a csv page through catalyst
sub send_hashes_as_csv_page
{
    my ( $c, $hashes, $title ) = @_;

    my $encoded_output = get_hashes_as_encoded_csv( $hashes );

    $c->res->header( 'Content-Disposition', qq[attachment; filename="$title"] );
    $c->res->header( 'Content-Length',      bytes::length( $encoded_output ) );
    $c->res->content_type( 'text/csv; charset=UTF-8' );
    $c->res->body( $encoded_output );
}

# given a file name, open the file, parse it as a csv, and return a list of hashes.
# assumes that the csv includes a header line.
sub get_csv_as_hashes
{
    my ( $file ) = @_;

    my $csv = Text::CSV_XS->new( { binary => 1, sep_char => "," } )
      || die "error using CSV_XS: " . Text::CSV_XS->error_diag();

    open my $fh, "<:encoding(utf8)", $file || die "Unable to open file $file: $!\n";

    $csv->column_names( $csv->getline( $fh ) );

    my $hashes = [];
    while ( my $hash = $csv->getline_hr( $fh ) )
    {
        push( @{ $hashes }, $hash );
    }

    return $hashes;
}

1;
