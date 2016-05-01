#!/usr/bin/env perl

use strict;
use warnings;

BEGIN
{
    use FindBin;
    use lib "$FindBin::Bin";
    use lib "$FindBin::Bin/../lib";
    use Catalyst::Test 'MediaWords';
}

use JSON;

use List::MoreUtils "uniq";
use List::Util "shuffle";

use Math::Prime::Util;

use Modern::Perl "2015";

use MediaWords;

use MediaWords::CM::Dump;

use MediaWords::CommonLibs;

use MediaWords::Pg::Schema;

use MediaWords::Test::DB;

use MediaWords::Util::Web;

use Readonly;

use Test::More;

Readonly my $TEST_API_KEY => 'f66a50230d54afaf18822808aed649f1d6ca72b08fb06d5efb6247afe9fbae52';

Readonly my $TEST_HTTP_SERVER_PORT => '3000';

Readonly my $TEST_HTTP_SERVER_URL => 'http://localhost:' . $TEST_HTTP_SERVER_PORT;

sub add_controversy_link
{
    my ( $db, $controversy, $story, $ref_story ) = @_;

    $db->create(
        'controversy_links',
        {
            controversies_id => $controversy->{ controversies_id },
            stories_id       => $story,
            url              => 'http://foo',
            redirect_url     => 'http://foo',
            ref_stories_id   => $ref_story,
        }
    );

}

sub add_controversy_story
{
    my ( $db, $controversy, $story ) = @_;

    $db->create( 'controversy_stories',
        { stories_id => $story->{ stories_id }, controversies_id => $controversy->{ controversies_id } } );
}

sub _api_request_url($;$)
{
    my ( $path, $params ) = @_;

    my $uri = URI->new( $path );

    $uri->query_param( 'key' => $TEST_API_KEY );

    if ( $params )
    {
        foreach my $key ( keys %{ $params } )
        {
            $uri->query_param( $key => $params->{ $key } );
        }
    }

    return $uri->as_string;
}

sub create_stories
{
    my ( $db, $stories, $controversies ) = @_;

    my $media = MediaWords::Test::DB::create_test_story_stack( $db, $stories );

}

sub create_test_database
{
    my $base_db = DBIx::Simple::MediaWords->connect( MediaWords::DB::connect_info );

    my $test_db_name = 'topics_api_test';

    # print "creating database $test_db_name ...\n";
    $base_db->query( "create database $test_db_name" );

    $base_db->disconnect();

    my $test_connect_info = [ MediaWords::DB::connect_info ];
    $test_connect_info->[ 0 ] =~ s/dbname=[a-z0-9_]*/dbname=$test_db_name/i;

    # print "connecting to test database: $test_connect_info->[0] ...\n";
    my $test_db = DBIx::Simple::MediaWords->connect( @{ $test_connect_info } );

    if ( !open( FILE, "$FindBin::Bin/script/mediawords.sql" ) )
    {
        die( "Unable to open schema file: $!" );
    }

    my $schema_sql = join( "\n", ( <FILE> ) );

    close( FILE );

    $test_db->query( $schema_sql );
    $test_db->query( MediaWords::Pg::Schema::get_sql_function_definitions() );

    # make sure the stories table exists as a sanity check for the schema
    $test_db->query( "select * from stories" );

    return ( $test_db, $test_db_name, $test_connect_info );
}

sub create_test_data
{

    my ( $test_db, $controversy_media_sources ) = @_;

    my $NUM_LINKS_PER_PAGE = 10;

    srand( 3 );

    my $test_db = shift;

    # populate controversies table
    my $controversy = $test_db->create(
        'controversies',
        {
            name                => 'foo',
            solr_seed_query     => '',
            solr_seed_query_run => 'f',
            pattern             => '',
            description         => 'test controversy'
        }
    );

    my $controversy_dates = $test_db->create(
        'controversy_dates',
        {
            controversies_id => $controversy->{ controversies_id },
            start_date       => '2014-04-01',
            end_date         => '2014-06-01'
        }
    );

    # populate controversies_stories table
    # only include stories with id not multiples of 3
    my $all_stories         = {};
    my $controversy_stories = [];

    for my $m ( values( %{ $controversy_media_sources } ) )
    {
        for my $f ( values( %{ $m->{ feeds } } ) )
        {
            while ( my ( $num, $story ) = each( %{ $f->{ stories } } ) )
            {
                if ( $num % 6 )
                {
                    my $cs = add_controversy_story( $test_db, $controversy, $story );
                    push @{ $controversy_stories }, $story->{ stories_id };
                }
                $all_stories->{ int( $num ) } = $story->{ stories_id };
            }
        }
    }

    # populate controversies_links table
    while ( my ( $num, $story_id ) = each %{ $all_stories } )
    {
        my @factors = Math::Prime::Util::factor( $num );
        foreach my $factor ( uniq @factors )
        {
            if ( $factor != $num )
            {
                add_controversy_link( $test_db, $controversy, $all_stories->{ $factor }, $story_id );
            }
        }
    }

    MediaWords::CM::Dump::dump_controversy( $test_db, $controversy->{ controversies_id } );

}

sub _get_test_response
{

    my $base_url = shift;

    my $url = _api_request_url( $base_url->{ path }, $base_url->{ params } );

    my $response = request( $url );

}

sub test_media_list
{
    my $data = shift;

    my $base_url = { path => '/api/v2/topics/1/media/list' };

    my $response = _get_test_response( $base_url );

    Test::More::ok( $response->is_success, 'Request should succeed' );

    my $actual_response = JSON::decode_json( $response->decoded_content() );

    ok( scalar @{ $actual_response->{ media } } == 3,
        "returned unexpected number of media scalar $actual_response->{ media }" );

    # Check descending link count
    foreach my $m ( 1 .. $#{ $actual_response->{ media } } )
    {
        ok( $actual_response->{ media }[ $m ]->{ inlink_count } <= $actual_response->{ media }[ $m - 1 ]->{ inlink_count } );
    }

    # Check that we have right number of inlink counts for each media source

    my $controversy_stories = _get_story_link_counts( $data );

    my $inlink_counts = {};
    for my $m ( keys %{ $data } )
    {
        for my $f ( values $data->{ $m } )
        {
            foreach my $num ( @{ $f } )
            {
                if ( exists $inlink_counts->{ $m } && $num % 6 )
                {
                    $inlink_counts->{ $m } += $controversy_stories->{ "story $num" };
                }
                else
                {
                    $inlink_counts->{ $m } = $controversy_stories->{ "story $num" };
                }
            }
        }
    }

    foreach my $mediasource ( @{ $actual_response->{ media } } )
    {
        ok( $mediasource->{ inlink_count } == $inlink_counts->{ $mediasource->{ name } } );
    }
}

sub test_story_count
{

    # The number of stories returned in stories/list matches the count in cdts

    my $base_url = { path => '/api/v2/topics/1/stories/list' };

    my $response = _get_test_response( $base_url );

    Test::More::ok( $response->is_success, 'Request should succeed' );

    my $actual_response = JSON::decode_json( $response->decoded_content() );

    Test::More::ok( $actual_response->{ timeslice }->{ story_count } + 0 == scalar @{ $actual_response->{ stories } } );

}

sub _get_story_link_counts
{
    my $data = shift;

    # umber of prime factors outside the media source
    my $counts = {
        1  => 0,
        2  => 0,
        3  => 0,
        4  => 0,
        5  => 0,
        7  => 0,
        8  => 1,
        9  => 1,
        10 => 2,
        11 => 0,
        13 => 0,
        14 => 2,
        15 => 0
    };

    my %return_counts = map { "story " . $_ => $counts->{ $_ } } keys %{ $counts };
    return \%return_counts;

}

sub test_story_inclusion
{

    # Make sure that only expected stories are in stories list response
    # Make sure that the order is inlink count descending
    my $data = shift;

    my $base_url = { path => '/api/v2/topics/1/stories/list' };

    my $controversy_stories = _get_story_link_counts( $data );

    my $response = _get_test_response( $base_url );

    my $actual_response = JSON::decode_json( $response->decoded_content() );

    my %actual_stories;
    my @actual_stories_order;

    foreach my $story ( @{ $actual_response->{ stories } } )
    {
        $actual_stories{ $story->{ 'title' } } = $story->{ 'inlink_count' };
        my @story_info = ( $story->{ 'inlink_count' }, $story->{ 'stories_id' } );
        push @actual_stories_order, \@story_info;
    }

    is_deeply( \%actual_stories, $controversy_stories, 'expected stories' );

    foreach my $story ( 1 .. $#actual_stories_order )
    {
        ok( $actual_stories_order[ $story ][ 0 ] <= $actual_stories_order[ $story - 1 ][ 0 ] );
        if ( $actual_stories_order[ $story ][ 0 ] == $actual_stories_order[ $story - 1 ][ 0 ] )
        {
            ok( $actual_stories_order[ $story ][ 1 ] > $actual_stories_order[ $story - 1 ][ 1 ] );
        }
    }
}

sub main
{
    MediaWords::Test::DB::test_on_test_database(
        sub {

            my $db = shift;

            my $stories = {
                A => {
                    B => [ 1, 2, 3 ],
                    C => [ 4, 5, 6, 15 ]
                },
                D => { E => [ 7, 8, 9 ] },
                F => {
                    G => [ 10, ],
                    H => [ 11, 12, 13, 14, ]
                }
            };

            my $controversy_media = create_stories( $db, $stories );

            create_test_data( $db, $controversy_media );

            test_story_count();
            test_story_inclusion( $stories );
            test_media_list( $stories );
            done_testing();
        }
    );
}

main();