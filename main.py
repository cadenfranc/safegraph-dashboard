import streamlit as st
from st_aggrid import GridOptionsBuilder, AgGrid
import plotly.express as px
import plotly.graph_objects as go
from datetime import date
import pandas as pd
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport
import base64

def display_gif(filename):
    f = open(filename, "rb")
    contents = f.read()
    data_url = base64.b64encode(contents).decode("utf-8")
    f.close()

    st.markdown(
        f'<img width = 700 src="data:image/gif;base64,{data_url}" loop="infinite">',
        unsafe_allow_html=True,
    )

@st.cache(allow_output_mutation=True)
def query_data(api_key):
    places_df = pd.DataFrame()
    patterns_df = pd.DataFrame()

    transport = RequestsHTTPTransport(
        url='https://api.safegraph.com/v2/graphql',
        verify=True,
        headers={'Content-Type': 'application/json', 'apikey': api_key}
        )

    client = Client(
        transport=transport, 
        fetch_schema_from_transport=True
        )

    places_query = """
        query {
        search(filter: { 
            address: {
                region: "ID"
                city: "Rexburg"
            }
        }){
            places {
            results(first: 500 after: "") {
                pageInfo { hasNextPage, endCursor}
                edges {
                node {
                    safegraph_core {
                        placekey
                        location_name
                        street_address
                        latitude
                        longitude
                        }
                }
                }
            }
            }
        }
        }
        """

    places = client.execute(gql(places_query))
    places = [n.pop('safegraph_core') \
        for n in [n.pop('node') \
            for n in places['search']['places']['results']['edges']]]
    for row in places:
        if row is not None:
            places_df = places_df.append(row, ignore_index=True)

    for day in pd.date_range("2022-01-01", date.today(), freq="W"):
        patterns_query = """
        query {
        search(filter: { 
            address: {
                region: "ID"
                city: "Rexburg"
            }
        }){
            places {
            results(first: 500 after: "") {
                pageInfo { hasNextPage, endCursor}
                edges {
                node {
                    safegraph_weekly_patterns (date: "%") {
                    placekey
                    location_name
                    date_range_start
                    raw_visit_counts
                    distance_from_home
                    median_dwell
                    visits_by_each_hour {
                        visits
                    }
                    bucketed_dwell_times
                    related_same_day_brand
                    }
                }
                }
            }
            }
        }
        }
        """
        patterns_query = patterns_query.replace("%", day.strftime("%Y-%m-%d"))

        patterns = client.execute(gql(patterns_query))
        patterns = [n.pop('safegraph_weekly_patterns') \
            for n in [n.pop('node') \
                for n in patterns['search']['places']['results']['edges']]]

        for row in patterns:
            if row is not None:
                patterns_df = patterns_df.append(row, ignore_index=True)

    visits = patterns_df[['placekey', 'raw_visit_counts']]\
        .groupby('placekey')\
        .sum()\
        .reset_index()

    return places_df.merge(visits), patterns_df


def main():
    st.title("SafeGraph Analytics Dashboard")
    api_key = st.text_input(
        "Please input your SafeGraph API Key to continue: ", 
        type="password")

    if api_key == "":
        display_gif("api.gif")

    else:
        places, patterns = query_data(api_key)
        st.info('Please select the places you would like to explore.')
        
        ob = GridOptionsBuilder.from_dataframe(places)
        ob.configure_selection('multiple', use_checkbox=True)
        ob.configure_side_bar(filters_panel = True)
        gridOptions = ob.build()

        grid = AgGrid(
            places,
            gridOptions,
            data_return_mode='AS_INPUT', 
            update_mode='MODEL_CHANGED', 
            fit_columns_on_grid_load=False,
            enable_enterprise_modules=True,
            theme='material',
            height=400, 
            width='100%'
        )

        selected_places = pd.DataFrame(grid['selected_rows'])

        num_places = len(selected_places)
        if num_places > 0:
            st.header("Weekly Traffic Analysis")
            st.markdown(f'{num_places} place(s) selected: **' +
                ', '.join(selected_places["location_name"].values) + '**')
            col1, col2 = st.columns([1, 2])
            col1.map(selected_places)

            data = patterns[patterns['placekey'].isin(selected_places['placekey'].values)]
            data['date_range_start'] = pd.to_datetime(data['date_range_start'])

            fig = px.line(
                data, 
                x="date_range_start", 
                y="raw_visit_counts", 
                color="placekey",
                title="Weekly Visit Count",
                width=850,
                height=300,
                markers={"opacity": 0.5, "size": 10}
            ).update_layout(
                margin=go.layout.Margin(l=30, r=0, b=0, t=40),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )

            col2.write(fig)

            pbh_totals = {key: value for key, value in zip(range(0, 24), [0]*24)}
            for row in data['visits_by_each_hour']:
                for i, hour in enumerate(row):
                    pbh_totals[i%24] += hour['visits']
            
            pbh_totals_df = pd.DataFrame(pbh_totals, index=[0])\
                .transpose()\
                .reset_index()\
                .sort_values(by=0, ascending=False)
            pbh_totals_df.columns = ['hour', 'total_visits']

            col2.write(
                px.bar(
                    pbh_totals_df, 
                    x='hour', 
                    y='total_visits', 
                    title='Hourly Visit Count',
                    width=850,
                    height=215,
                ).update_layout(
                    margin=go.layout.Margin(l=30, r=0, b=0, t=40)
                )
                )

            st.header("Additional Location Insights")
            st.write("The following insights are available for the selected locations.")

            st.markdown('People tend to spend approximately **' +
                str(round(data['median_dwell'].mean(), 2)) +
                ' minutes** at these locations.')

            st.markdown('They travel an average of **' +
                str(round(data['distance_from_home'].mean() / 1000, 2)) +
                ' kilometers** from home to get to these locations.')

            rsdb_totals = dict()
            for row in data['related_same_day_brand']:
                for place in row:
                    if place not in rsdb_totals:
                        rsdb_totals[place] = row[place]
                    else:
                        rsdb_totals[place] += row[place]
            
            rsdb_totals_df = pd.DataFrame(rsdb_totals, index=[0])\
                .transpose()\
                .reset_index()\
                .sort_values(by=0, ascending=False)\
                .head(20)
            rsdb_totals_df.columns = ['location_name', 'total_visits']

            st.write(
                px.bar(
                    rsdb_totals_df, 
                    x='location_name', 
                    y='total_visits', 
                    title='Top 20 Related Same Day Brand Visits',
                ).update_layout(
                    margin=go.layout.Margin(l=30, r=0, b=0, t=40)
                )
                )

        else:
            st.map(places)

if __name__ == "__main__":
    main()